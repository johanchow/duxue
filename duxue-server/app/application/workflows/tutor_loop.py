"""tutor-turn.v4 的模型循环与出口检查，不依赖数据库。

生产的 TutoringWorkflow 与离线评测（``evals/``）共用这里的代码：评测看到的
fallback 与线上完全同源，不另抄一份规则。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.application.workflows.tutor_shape import lint_shape
from app.application.workflows.tutor_tools import (
    MAX_MODEL_CALLS,
    MAX_TOOL_CALLS,
    SVG_WIDGET_GUIDELINES,
    TutorToolbox,
)
from app.application.workflows.tutor_turn import (
    LeakJudgePort,
    TutorModelPort,
    TutorTurnCandidate,
    Verdict,
    check_authority,
    format_schema_error,
    schema_error_diagnostic,
)
from app.application.workflows.tutor_visual import Visual, describe
from app.contexts.tutoring.domain.tutor_permit import TutorPermit
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.observability.telemetry import (
    record_llm_fallback,
    record_tutor_candidate_rejection,
    record_tutor_fact_gate,
    record_tutor_leak_retry,
    record_tutor_shape_lint,
    record_tutor_visual_dropped,
)

INVALID_CANDIDATE = "invalid_model_candidate"
_VISUAL_REPAIR_DRAFT_MAX = 4000


def _ensure_widget_guidelines(observations: list[dict]) -> None:
    if any(item.get("tool") == "widget_guidelines" for item in observations):
        return
    observations.append({
        "tool": "widget_guidelines", "status": "unique", "guidelines": SVG_WIDGET_GUIDELINES,
    })


def _visual_repair(candidate: TutorTurnCandidate, raw: dict, *, reason: str | None = None) -> str:
    draft = {key: raw[key] for key in ("act", "content", "turn", "visual") if key in raw}
    rejected = json.dumps(draft, ensure_ascii=False)
    if len(rejected) > _VISUAL_REPAIR_DRAFT_MAX:
        rejected = rejected[:_VISUAL_REPAIR_DRAFT_MAX] + "…"
    return (
        f"visual 校验未通过（{reason or candidate.visual_error}）；请保持 act、content、turn 不变，只修正 visual。"
        f"\n被拒草稿（只供改写 visual，禁止改动正文）：{rejected}"
    )


@dataclass(frozen=True)
class ModelCall:
    """主调用的结果：候选，或没有候选的原因（只含类别，不含儿童内容）。"""

    candidate: TutorTurnCandidate | None
    failure: str | None = None


@dataclass(frozen=True)
class Vetting:
    """出口检查的结果。``failure`` 为空表示候选可以投影给 Ward。

    ``visual`` 是通过检查、可以展示的图；``visual_dropped`` 是图被丢弃的原因（图丢弃不是失败，文字照常展示）。
    ``shape_flags`` 只是观测，不影响展示。
    """

    candidate: TutorTurnCandidate
    verdict: Verdict | None
    failure: str | None = None
    leak_reason: str | None = None
    visual: Visual | None = None
    visual_dropped: str | None = None
    shape_flags: list[str] = field(default_factory=list)


def call_tutor_model(
    model: TutorModelPort, envelope: dict, instruction: str, window: list[dict],
    images: list, tools: TutorToolbox, *, repair_error: str | None = None,
    preload_svg_guidelines: bool = False,
) -> ModelCall:
    """有界循环：模型要工具就执行，直到返回候选。

    至多 MAX_TOOL_CALLS 次工具、MAX_MODEL_CALLS 次主调用（含结构重试）。
    ``repair_error`` 预置时（泄露后的重试）本身就是那一次重试，结构再错不另行重试。
    不记录 fallback：一轮是否回退由 ``run_tutor_turn`` 按最终结果判断。
    """
    repair: str | None = repair_error
    observations: list[dict] = []
    if preload_svg_guidelines:
        _ensure_widget_guidelines(observations)
    tool_calls = 0
    best_candidate: TutorTurnCandidate | None = None
    for _ in range(MAX_MODEL_CALLS):
        try:
            raw = model.complete(
                envelope=envelope, instruction=instruction, recent_utterances=window,
                current_images=images, repair_error=repair, observations=observations,
            )
        except ModelGatewayError as error:
            # json.loads() lives in the provider adapter.  An empty string
            # or malformed JSON gets here before Pydantic can issue its
            # usual repair request, but it deserves the same one retry.
            if str(error) == "invalid_model_candidate" and repair is None:
                record_tutor_candidate_rejection(
                    error_type="invalid_json", field="root", retrying=True,
                )
                repair = "返回的内容不是有效 JSON 对象；只返回一个符合 tutor-turn.v4 的 JSON 对象。"
                continue
            if best_candidate is not None:
                return ModelCall(best_candidate)
            return ModelCall(None, str(error))
        except Exception as error:  # noqa: BLE001 - provider failures must fall back safely.
            if best_candidate is not None:
                return ModelCall(best_candidate)
            return ModelCall(None, str(error))
        if isinstance(raw, dict) and "tool" in raw:
            name = str(raw.get("tool"))
            if tool_calls >= MAX_TOOL_CALLS:
                observations.append({"tool": name, "status": "budget_exhausted"})
            else:
                tool_calls += 1
                observations.append(tools.run(name, raw.get("args")))
            continue
        try:
            candidate = TutorTurnCandidate.model_validate(raw)
        except (ValidationError, ValueError) as error:
            error_type, field = schema_error_diagnostic(error)
            record_tutor_candidate_rejection(
                error_type=error_type, field=field, retrying=repair is None,
            )
            if repair is not None:  # 结构错误只重试一次
                break
            repair = format_schema_error(error)
            continue
        if (
            candidate.visual_dropped == "visual_invalid"
            and candidate.visual_error
            and repair is None
        ):
            best_candidate = candidate
            if isinstance(raw.get("visual"), dict) and raw["visual"].get("kind") == "svg":
                _ensure_widget_guidelines(observations)
            repair = _visual_repair(candidate, raw)
            continue
        if (
            candidate.visual is not None
            and candidate.visual.kind == "svg"
            and not any(item.get("tool") == "widget_guidelines" for item in observations)
        ):
            # A syntactically valid SVG may still have the wrong diagram geometry.
            # Require the design system before accepting a model-drawn vector.
            best_candidate = candidate.model_copy(update={
                "visual": None, "visual_dropped": "visual_invalid",
                "visual_error": "svg generated without widget_guidelines",
            })
            if repair is not None:
                return ModelCall(best_candidate)
            _ensure_widget_guidelines(observations)
            repair = _visual_repair(candidate, raw, reason="未先加载 widget_guidelines 中的绘图规范")
            continue
        if best_candidate is not None and (
            candidate.act != best_candidate.act
            or candidate.content != best_candidate.content
            or candidate.turn != best_candidate.turn
        ):
            return ModelCall(best_candidate)
        return ModelCall(candidate)
    if best_candidate is not None:
        return ModelCall(best_candidate)
    return ModelCall(None, INVALID_CANDIDATE)


def _check_visual_leak(leak_judge: LeakJudgePort, text: str, task_title, problem_summary) -> bool | None:
    """图泄露判官。任何异常都按"判不准"处理：图判不准只丢图，不影响文字。"""
    judge = getattr(leak_judge, "visual_leaks", None)
    if judge is None:
        return None
    try:
        return judge(text=text, task_title=task_title, problem_summary=problem_summary)
    except Exception:  # noqa: BLE001 - a broken judge must never become a shown diagram.
        return None


# 短事实分类的长度上限（字）；受保护题目的正文无论分类结果都交独立审核。
FACT_REPLY_MAX_CHARS = 120
# 判官看到本答疑会话最近这么多道题：`relation=new` 放弃的题不受保护，但孩子随后追问它的答案时，
# 判官必须还能认出来。
JUDGE_RECENT_PROBLEMS = 3
JUDGE_RECENT_STUDENT_UTTERANCES = 3
# 越过作业答案边界时重试一次；判官自身失败不重试。
LEAK_RETRY_REASONS = frozenset({"leak_detected"})
LEAK_REPAIR = "泄露：上一版回复越过了作业答案边界；请按题型重写，不附和错误答案或确认可试探的选项。"
VISUAL_LEAK_REPAIR = (
    "visual 泄露审核未通过：重画一张辅助图。尽量只摆题面已知量，可有少量过程描述；"
    "最终待求量用 ?，不要直接暴露答案或替学生完成关键计算。"
    "保持 act、content、turn 原样，只修改 visual。"
)
MISSING_VISUAL_REPAIR = (
    "上一版把二维竖式写成了 TeX 文字，没有返回 visual，App 无法显示该图形。"
    "请使用已给的 widget_guidelines 返回 kind=svg 的 visual；保持 act、turn 与题目数字不变，"
    "把 content 中的 TeX 竖式去掉，保留简短、可独立阅读的文字引导。商位用 ?。"
)
_TEXT_DIAGRAM_TEX = r"\enclose{longdiv}"


def judge_problem_summary(
    recent_problems: list[str], student_said: str, *, recent_utterances: list[dict] | None = None,
) -> str | None:
    """审核题目及有界学生证据；导师原话不当作学生已经提交的答案。"""
    problems = [item.strip() for item in recent_problems if item and item.strip()][:JUDGE_RECENT_PROBLEMS]
    lines = [f"第{index}题：{item}" for index, item in enumerate(problems, start=1)]
    ward_texts = [str(item.get("text", "")).strip() for item in (recent_utterances or [])
                  if item.get("author") == "ward" and str(item.get("text", "")).strip()]
    lines.extend(f"学生先前说：{text[:300]}" for text in ward_texts[-JUDGE_RECENT_STUDENT_UTTERANCES:])
    if student_said.strip() and student_said.strip() not in problems:
        lines.append(f"孩子本轮说：{student_said.strip()}")
    return "\n".join(lines) or None


LEAK_REASONS = frozenset({
    "final_answer", "complete_solution", "choice_verdict", "incorrect_confirmation",
    "premature_conclusion",
})


def _text_leak_result(result: bool | dict | None) -> tuple[bool | None, str | None]:
    if isinstance(result, bool):
        return result, None
    if isinstance(result, dict) and isinstance(result.get("leaks"), bool):
        reason = result.get("reason")
        return result["leaks"], reason if result["leaks"] and isinstance(reason, str) and reason in LEAK_REASONS else None
    return None, None


def _leak_repair(vetting: Vetting) -> str:
    """Bounded feedback for one retry. The rejected draft never reaches the child."""
    reason = vetting.leak_reason or vetting.failure or "unspecified"
    rejected = json.dumps(vetting.candidate.shown_text[:800], ensure_ascii=False)
    return f"{LEAK_REPAIR}\n审核原因：{reason}。\n被拒草稿（只供改写，禁止照抄）：{rejected}"


def _visual_leak_repair(vetting: Vetting) -> str:
    rejected = json.dumps(vetting.candidate.model_dump(mode="json"), ensure_ascii=False)
    if len(rejected) > _VISUAL_REPAIR_DRAFT_MAX:
        rejected = rejected[:_VISUAL_REPAIR_DRAFT_MAX] + "…"
    return f"{VISUAL_LEAK_REPAIR}\n被拒草稿（只供重画，禁止照抄图中泄露内容）：{rejected}"


def _missing_visual_repair(vetting: Vetting) -> str:
    draft = json.dumps(vetting.candidate.model_dump(mode="json"), ensure_ascii=False)
    if len(draft) > _VISUAL_REPAIR_DRAFT_MAX:
        draft = draft[:_VISUAL_REPAIR_DRAFT_MAX] + "…"
    return f"{MISSING_VISUAL_REPAIR}\n待修正草稿：{draft}"


def fact_gate(candidate: TutorTurnCandidate) -> str | None:
    """短事实分类，仅用于观测；返回 None 表示模型声明了短事实。

    模型自报的 atomic/recall/atomic_lookup 不能作为跳过受保护题目审核的权限。
    分类不看关键词或数字；受保护题目统一交独立判官审核。"""
    if candidate.depth not in {"atomic", "recall"} and candidate.topic != "atomic_lookup":
        return "not_fact"
    if len(candidate.content) > FACT_REPLY_MAX_CHARS:
        return "too_long"
    return None


def vet_candidate(
    candidate: TutorTurnCandidate, *, permit: TutorPermit, leak_judge: LeakJudgePort,
    task_title: str | None, problem_summary: str | None,
) -> Vetting:
    """检查 2（越权与一致性）和检查 3（泄露）。只判断，不记录 fallback（由 ``run_tutor_turn`` 按最终结果记）。

    文字（``content``，澄清时连同候选）任一不过，调用方回退固定话术。``fact_gate``
    仅分类观测，受保护正文都交判官审。图（``visual``）单独判断：不适用、非法、
    被图判官判为泄露（含超时、结果非法）一律只丢图，文字照常。
    """
    verdict = check_authority(candidate, permit)
    if not verdict.ok:
        return Vetting(candidate, verdict, verdict.reason)

    flags = lint_shape(candidate.act, candidate.content)
    if candidate.act == "answer" and candidate.depth == "reasoning":
        # 提示词要求推理题用 guide；不拒绝（泄露检查照跑），只留观测。
        flags.append("answer_on_reasoning")
    if flags:
        record_tutor_shape_lint(act=candidate.act, flags=flags)

    visual, dropped = candidate.visual, candidate.visual_dropped
    visual_text = describe(visual) if visual is not None else None

    text_leaks: bool | None = False
    visual_leaks: bool | None = False
    if verdict.needs_leak_check:
        gate = fact_gate(candidate)
        record_tutor_fact_gate(outcome=gate or "short_fact_reviewed")
        # The depth/topic labels come from the same model as the reply. A multiple-choice
        # confirmation can be mislabeled as a short "fact", so those labels cannot bypass
        # independent review while a problem is protected. Keep the classification metric.
        judge_text = True
        jobs = {}
        # 文字判官与图判官互不依赖，并行发出。
        with ThreadPoolExecutor(max_workers=2) as pool:
            if judge_text:
                jobs["text"] = pool.submit(
                    leak_judge.leaks, text=candidate.shown_text, task_title=task_title,
                    problem_summary=problem_summary,
                )
            if visual_text is not None:
                jobs["visual"] = pool.submit(
                    _check_visual_leak, leak_judge, visual_text, task_title, problem_summary,
                )
            text_leaks, leak_reason = _text_leak_result(jobs["text"].result()) if "text" in jobs else (False, None)
            visual_leaks = jobs["visual"].result() if "visual" in jobs else False
        if text_leaks is False and visual_leaks is not False:
            visual = None
            dropped = "visual_leak_check_failed" if visual_leaks is None else "visual_leak_detected"
    if text_leaks is not False:  # True 泄露；None 判定失败，同样 fail-closed
        reason = "leak_check_failed" if text_leaks is None else "leak_detected"
        return Vetting(candidate, None, reason, leak_reason=leak_reason, shape_flags=flags)
    if dropped:
        record_tutor_visual_dropped(reason=dropped)
    return Vetting(candidate, verdict, visual=visual, visual_dropped=dropped, shape_flags=flags)


@dataclass(frozen=True)
class TurnResult:
    """一轮的最终候选与出口检查结果。``leak_retried`` 表示第一版因给出答案被拦、已重试一次。"""

    call: ModelCall
    vetting: Vetting | None
    leak_retried: bool = False


def run_tutor_turn(
    model: TutorModelPort, envelope: dict, instruction: str, window: list[dict], images: list,
    tools: TutorToolbox, *, permit: TutorPermit, leak_judge: LeakJudgePort,
    task_title: str | None, problem_summary: str | None,
    backup_model: TutorModelPort | None = None,
) -> TurnResult:
    """主调用 + 出口检查；文字给出了答案时带 ``LEAK_REPAIR`` 重试一次，重试结果重新完整检查。

    生产与离线评测共用。``model_fallback`` 只按最终结果记录一次。"""
    def vet(candidate: TutorTurnCandidate) -> Vetting:
        return vet_candidate(
            candidate, permit=permit, leak_judge=leak_judge,
            task_title=task_title, problem_summary=problem_summary,
        )

    call = call_tutor_model(model, envelope, instruction, window, images, tools)
    if call.candidate is None:
        record_llm_fallback(operation="tutor_turn", reason=call.failure or INVALID_CANDIDATE)
        return TurnResult(call, None)
    vetting = vet(call.candidate)
    retried = False
    if vetting.failure in LEAK_RETRY_REASONS:
        original_failure, original_reason = vetting.failure, vetting.leak_reason
        retried = True
        record_tutor_leak_retry(reason=vetting.failure)
        retry = call_tutor_model(
            model, envelope, instruction, window, images, tools, repair_error=_leak_repair(vetting),
        )
        if retry.candidate is not None:
            call, vetting = retry, vet(retry.candidate)
        if (
            backup_model is not None
            and vetting.failure == original_failure == "leak_detected"
            and vetting.leak_reason == original_reason
        ):
            backup = call_tutor_model(
                backup_model, envelope, instruction, window, images, tools,
                repair_error=_leak_repair(vetting),
            )
            if backup.candidate is not None:
                call, vetting = backup, vet(backup.candidate)
    if vetting.failure is None and vetting.visual_dropped == "visual_leak_detected":
        redraw = call_tutor_model(
            model, envelope, instruction, window, images, tools,
            repair_error=_visual_leak_repair(vetting),
        )
        if redraw.candidate is not None:
            redrawn = vet(redraw.candidate)
            if (
                redrawn.failure is None and redrawn.visual is not None
                and redrawn.candidate.act == vetting.candidate.act
                and redrawn.candidate.content == vetting.candidate.content
                and redrawn.candidate.turn == vetting.candidate.turn
            ):
                call, vetting = redraw, redrawn
    if (
        vetting.failure is None and vetting.visual is None
        and _TEXT_DIAGRAM_TEX in vetting.candidate.content
    ):
        repair = _missing_visual_repair(vetting)
        for retry_model in (model, backup_model):
            if retry_model is None:
                continue
            redrawn_call = call_tutor_model(
                retry_model, envelope, instruction, window, images, tools,
                repair_error=repair, preload_svg_guidelines=True,
            )
            if redrawn_call.candidate is None:
                continue
            redrawn = vet(redrawn_call.candidate)
            if (
                redrawn.failure is None and redrawn.visual is not None
                and redrawn.visual.kind == "svg"
                and _TEXT_DIAGRAM_TEX not in redrawn.candidate.content
            ):
                call, vetting = redrawn_call, redrawn
                break
    if vetting.failure is not None:
        record_llm_fallback(operation="tutor_turn", reason=vetting.failure)
    return TurnResult(call, vetting, retried)
