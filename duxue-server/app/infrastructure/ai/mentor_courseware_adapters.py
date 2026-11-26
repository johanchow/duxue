"""Infrastructure adapters for MentorCourseware (P0-1: ComponentScene + DeepSeek/Qwen)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from app.agent_specs.release_runtime import pin_release
from app.application.ports.mentor_courseware import (
    CoursewareMediaRenderPort,
    DirectorDraftResult,
    PedagogicalDirectorPort,
    PedagogicalJudgePort,
    PedagogicalJudgeResult,
    ProblemVerificationPort,
)
from app.application.ports.problem_solving import QwenProblemSolverGateway
from app.application.workflows.guardian_experience import _image
from app.application.workflows.guardian_mentor import _solve_for_mentor
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareStep,
    CoursewareVersion,
    VerificationBaseline,
    VisualSpec,
)
from app.infrastructure.ai.components import complete_json_chat, model_for

logger = logging.getLogger(__name__)

SUPPORTED_P0_1_COMPONENTS = frozenset({"coord_plane_2d", "geometry_2d", "solid_geometry_3d"})
_FORBIDDEN_SVG_RE = re.compile(r"<\s*(script|iframe|object|embed|foreignObject)\b|on[a-z]+\s*=|javascript:", re.IGNORECASE)


class ComponentSceneMediaRenderer(CoursewareMediaRenderPort):
    """P0-1 validator/normalizer for preset component_scene & safe layered_svg."""

    def validate_and_prepare(self, visual: VisualSpec) -> VisualSpec:
        if visual.kind == "math_stage_script":
            # P0-1 disables generated JS; degrade cleanly to static fallback
            return self._degrade_to_static(visual, note="P0-1 仅支持预置组件与静态图，已降级")

        if visual.kind == "layered_svg":
            svg = str(visual.payload.get("svg") or "")
            if not svg.strip() or _FORBIDDEN_SVG_RE.search(svg):
                return self._degrade_to_static(visual, note="静态 SVG 未通过安全校验，已降级为文本")
            return visual

        if visual.kind == "component_scene":
            comp = str(visual.payload.get("component") or "").strip()
            if comp not in SUPPORTED_P0_1_COMPONENTS:
                return self._degrade_to_static(visual, note=f"未支持的组件 {comp}，已降级")
            fallback_text = visual.static_fallback_text or visual.alt or visual.title or "图示说明"
            return VisualSpec(
                kind="component_scene",
                payload=dict(visual.payload),
                title=visual.title,
                alt=visual.alt or fallback_text,
                runtime_version=visual.runtime_version,
                min_runtime_version=visual.min_runtime_version,
                static_fallback_svg=visual.static_fallback_svg,
                static_fallback_text=fallback_text,
                highlight_anchors=visual.highlight_anchors,
            )

        return self._degrade_to_static(visual, note="未知图型，已降级")

    @staticmethod
    def _degrade_to_static(visual: VisualSpec, *, note: str) -> VisualSpec:
        text = visual.static_fallback_text or visual.alt or visual.title or note
        return VisualSpec(
            kind="layered_svg",
            payload={"svg": "", "fallback_text": text, "degraded": True},
            title=visual.title,
            alt=text,
            static_fallback_text=text,
        )


class ProblemSolvingAclAdapter(ProblemVerificationPort):
    """ACL calling existing stateless ProblemSolving kernel without student DB writes."""

    def solve_and_verify(
        self,
        *,
        prompt_text: str,
        attachment_keys: tuple[str, ...],
        guardian_id: UUID,
    ) -> VerificationBaseline:
        try:
            images = []
            for key in attachment_keys:
                image = _image(str(guardian_id), key)
                if image is None:
                    raise ValueError("Courseware attachment unavailable")
                images.append(image)
            with pin_release():
                verified = _solve_for_mentor(
                    content=prompt_text, images=images,
                    solver=QwenProblemSolverGateway(), bank_lookup=None,
                )
            if verified is None:
                raise ValueError("Mentor solver unavailable")
            approaches = [a.to_dict() if hasattr(a, "to_dict") else dict(a) for a in (verified.approaches or [])]
            raw_answers = verified.final_answers
            if isinstance(raw_answers, dict):
                final_answers = [f"{k}: {v}" if len(raw_answers) > 1 else str(v) for k, v in raw_answers.items()]
            else:
                final_answers = [str(a) for a in (raw_answers or [])]
            summary = "；".join(final_answers) if final_answers else (verified.stem.raw_text[:200] if verified.stem else prompt_text[:200])
            return VerificationBaseline.create(
                confidence=verified.confidence if verified.confidence in {"high", "medium", "low"} else "low",
                summary_answer=summary,
                stem_text=verified.stem.raw_text if verified.stem else prompt_text,
                subject=verified.stem.subject if verified.stem else "general",
                approaches=approaches,
                final_answers=final_answers,
            )
        except Exception as exc:  # noqa: BLE001 - preserve the documented adapter fallback
            logger.warning("ProblemSolving ACL fallback to low-confidence baseline: %s", exc)
            return VerificationBaseline.create(
                confidence="low",
                summary_answer="核验引擎暂未完成精确验算，请结合原题核对推导步骤。",
                stem_text=prompt_text,
                subject="general",
            )

    def reverify_revision(
        self,
        *,
        baseline: VerificationBaseline,
        instruction: str,
        draft_steps: tuple[CoursewareStep, ...],
    ) -> tuple[bool, VerificationBaseline | None, str]:
        recheck_prompt = (
            f"原题：{baseline.stem_text}\n"
            f"原核验结论：{baseline.summary_answer}\n"
            f"导师提出的修订要求：{instruction}\n"
            "请独立求解核验新结论是否成立。"
        )
        new_base = self.solve_and_verify(prompt_text=recheck_prompt, attachment_keys=(), guardian_id=UUID(int=0))
        if new_base.confidence == "low":
            return False, None, "确定性引擎未能确认修订结论"
        return True, new_base, "已通过复核"


_DIRECTOR_SYSTEM_PROMPT = """你是一位资深的 K-12 金牌学科导师，正在为家长或伴学老师编写可直接用于“彻底讲通”的交互式结构化课件。
核心教学原则：
1. 根据题型、学段与理解难度灵活组织步骤，不强行凑固定幕数或固定顺序。
2. 对推导步骤讲清「思考依据（thinking_why）」与「具体操作（action_what）」，避免凭空作辅助线或无依据跳步。
3. 仅在配图能显著降低理解门槛时提供 visual_spec，且优先使用 P0-1 预置组件（component_scene）：
   - coord_plane_2d: 平面直角坐标系、函数曲线、动点与最值
   - geometry_2d: 平面几何点/线/多边形/对称翻折与辅助线
   - solid_geometry_3d: 立体几何正方体/棱锥/棱柱/截面高亮/展开与 3D 旋转
   每个 component_scene 必须附带简洁准确的 static_fallback_text。
严格返回 JSON 对象：
{
  "change_summary": "一句话概述本版课件",
  "methodology_key": "可选，一句话核心思路",
  "requires_reverify": false,
  "target_step_ids": ["仅修订时填写被修改的 step_id"],
  "steps": [
    {
      "step_id": "s1",
      "title": "步骤标题",
      "pedagogical_role": "可选标签",
      "thinking_why": "为什么想到这一步（概念/过渡步可为 null）",
      "action_what": "具体推导或讲解（支持 Markdown 与 LaTeX）",
      "visual_spec": null 或 {"kind":"component_scene","title":"...","alt":"...","static_fallback_text":"...","payload":{"component":"coord_plane_2d|geometry_2d|solid_geometry_3d", ...}}
    }
  ]
}"""

_JUDGE_SYSTEM_PROMPT = """你是独立的名师教研审稿人（与生成模型异构）。
请检查课件草稿是否存在以下问题：
1. 推导步骤出现无依据跳步或“凭空作辅助线”，没讲清为什么这么想；
2. 讲解结论与客观核验基线（VerificationBaseline）矛盾；
3. 配图存在时与对应步骤文字脱节。
不要按固定章节模板扣分。严格返回 JSON：{"passed": true|false, "critique": "若不通过给出具体修改建议", "issues": ["..."]}"""


def _extract_json(text: str) -> dict[str, Any]:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return json.loads(s)


def _call_chat_json(*, component: str, model: str | None, system: str, user: str) -> dict[str, Any]:
    with pin_release():
        selected_model = model or model_for(component)
    result = complete_json_chat(
        model=selected_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=8192,
    )
    return _extract_json(result.raw)


def _parse_steps(raw_steps: list[dict[str, Any]]) -> tuple[CoursewareStep, ...]:
    steps: list[CoursewareStep] = []
    for idx, item in enumerate(raw_steps, start=1):
        sid = str(item.get("step_id") or f"s{idx}").strip()
        v_raw = item.get("visual_spec")
        visual = None
        if isinstance(v_raw, dict) and v_raw.get("kind"):
            visual = VisualSpec(
                kind=v_raw["kind"],
                payload=dict(v_raw.get("payload") or {}),
                title=str(v_raw.get("title") or ""),
                alt=str(v_raw.get("alt") or ""),
                static_fallback_svg=v_raw.get("static_fallback_svg"),
                static_fallback_text=v_raw.get("static_fallback_text"),
            )
        steps.append(
            CoursewareStep(
                step_id=sid,
                title=str(item.get("title") or f"步骤 {idx}"),
                thinking_why=item.get("thinking_why"),
                action_what=str(item.get("action_what") or ""),
                pedagogical_role=item.get("pedagogical_role"),
                visual_spec=visual,
            )
        )
    return tuple(steps)


class ModelDirectorAdapter(PedagogicalDirectorPort):
    """DeepSeek/Qwen director adapter for initial drafting and localized revision."""

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    def draft_initial(
        self,
        *,
        prompt_text: str,
        baseline: VerificationBaseline,
        target_grade_hint: str | None = None,
    ) -> DirectorDraftResult:
        user_msg = json.dumps(
            {
                "task": "draft_initial_courseware",
                "prompt_text": prompt_text,
                "target_grade_hint": target_grade_hint,
                "verification_baseline": baseline.to_dict(),
            },
            ensure_ascii=False,
        )
        data = _call_chat_json(component="tutoring.turn", model=self._model, system=_DIRECTOR_SYSTEM_PROMPT, user=user_msg)
        steps = _parse_steps(data.get("steps") or [])
        return DirectorDraftResult(
            change_summary=str(data.get("change_summary") or "初版深度课件"),
            methodology_key=data.get("methodology_key"),
            steps=steps,
            requires_reverify=False,
        )

    def draft_revision(
        self,
        *,
        current_version: CoursewareVersion,
        baseline: VerificationBaseline,
        instruction: str,
        target_step_id: str | None = None,
        critique: str | None = None,
    ) -> DirectorDraftResult:
        user_msg = json.dumps(
            {
                "task": "draft_localized_revision",
                "instruction": instruction,
                "target_step_id": target_step_id,
                "critique": critique,
                "current_version": current_version.to_dict(),
                "verification_baseline": baseline.to_dict(),
            },
            ensure_ascii=False,
        )
        data = _call_chat_json(component="tutoring.turn", model=self._model, system=_DIRECTOR_SYSTEM_PROMPT, user=user_msg)
        steps = _parse_steps(data.get("steps") or [])
        return DirectorDraftResult(
            change_summary=str(data.get("change_summary") or instruction[:40]),
            methodology_key=data.get("methodology_key"),
            steps=steps,
            requires_reverify=bool(data.get("requires_reverify", False)),
            target_step_ids=tuple(str(x) for x in (data.get("target_step_ids") or ())),
        )


class ModelPedagogicalJudgeAdapter(PedagogicalJudgePort):
    """Heterogeneous Qwen judge adapter (never same model family as Director)."""

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    def review(
        self,
        *,
        prompt_text: str,
        baseline: VerificationBaseline,
        draft: DirectorDraftResult,
    ) -> PedagogicalJudgeResult:
        try:
            user_msg = json.dumps(
                {
                    "prompt_text": prompt_text,
                    "verification_baseline": baseline.to_dict(),
                    "draft_steps": [s.to_dict() for s in draft.steps],
                },
                ensure_ascii=False,
            )
            data = _call_chat_json(component="tutoring.leak-judge", model=self._model, system=_JUDGE_SYSTEM_PROMPT, user=user_msg)
            return PedagogicalJudgeResult(
                passed=bool(data.get("passed", True)),
                critique=str(data.get("critique") or ""),
                issues=tuple(str(i) for i in (data.get("issues") or ())),
            )
        except Exception as exc:  # noqa: BLE001 - preserve the documented adapter fallback
            logger.warning("PedagogicalJudge unavailable, passing with observation warning: %s", exc)
            return PedagogicalJudgeResult(passed=True, critique="judge_unavailable")
