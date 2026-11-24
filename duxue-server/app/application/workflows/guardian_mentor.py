"""Adult Guardian mentor-explanation workflow (`guardian_explain`).

Strictly isolated from student `TutoringWorkflow`, `run_tutor_turn`, and `TutorPermitPolicy`:
- Reuses `ProblemSolving` (`solve_and_verify_problem` + optional `scope='bank'` read-only query)
  outside DB transactions with zero student-domain writes.
- Enforces the Confidence Honesty Gate, Visual schema/safety whitelist, pronunciation checks,
  and bidirectional `LocalSafetyScreening`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from openai import APIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agent_specs.guardian_contracts import (
    DEFAULT_MENTOR_PROMPT,
    MENTOR_BLUEPRINT,
    MENTOR_CONTENT_MAX_LENGTH,
    MENTOR_EXPLAIN_ID,
    MENTOR_FINISH,
    MENTOR_PARENT_BRANCHES,
    MENTOR_PREPARE,
    MENTOR_REVIEW_PROMPT,
    MENTOR_WORKFLOW_ID,
)
from app.application.commands.problem_solving import (
    VerifiedSolution,
    solve_and_verify_problem,
)
from app.application.ports.problem_solving import (
    ProblemSolverModelPort,
    QwenProblemSolverGateway,
)
from app.application.queries.run_transcript import select_recent_utterances
from app.application.workflows.image_target import prepare_images
from app.application.workflows.pronunciation_guidance import (
    LessonBody,
    forbidden_text,
    normalized,
)
from app.application.workflows.tutor_turn import (
    FALLBACK_TEXT,
    SAFE_TEXT,
    PronouncePayload,
    fallback_text,
)
from app.application.workflows.tutor_visual import (
    VISUAL_ADAPTER,
    Visual,
    describe,
    drop_reason,
)
from app.contexts.problem_solving.domain.dossier import (
    ProblemDossier,
    StructuredStem,
)
from app.infrastructure.ai.client import remaining_model_time
from app.infrastructure.ai.errors import ModelGatewayError, ModelTimeBudgetExceeded
from app.infrastructure.ai.tutoring_safety import LocalSafetyScreening
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from app.infrastructure.security.experience_tokens import seal

MentorAct = Literal["explain", "answer", "clarify", "pronounce", "safety"]
MENTOR_PURPOSE = "conversation_mentor"

_CONDITION_CONFIRM_PREFIX = (
    "> **题面核对提示**：原图或题干关键条件存在模糊或不同读法，以下先按当前识别条件给出破题思路框架，"
    "请先对照原题核实数值与符号。\n\n"
)
_LOW_CONFIDENCE_PREFIX = (
    "> **核验状态说明**：关键计算尚未得到引擎充分核验。请结合原题查看以下解析。\n\n"
)


class MentorRateLimitExceeded(Exception):
    """Raised when an adult account exceeds the bounded mentor-explanation quota."""


class MentorRateLimiter:
    """Bounded per-account sliding-window rate limiter against automated homework scraping."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._minute_hits: dict[str, deque[float]] = {}
        self._day_hits: dict[str, deque[float]] = {}
        self.per_minute: int = int(os.getenv("GUARDIAN_MENTOR_LIMIT_PER_MINUTE", "8"))
        self.per_day: int = int(os.getenv("GUARDIAN_MENTOR_LIMIT_PER_DAY", "40"))

    def check_and_record(self, guardian_id: str, *, now_ts: float | None = None) -> None:
        ts = time.monotonic() if now_ts is None else now_ts
        with self._lock:
            m_q = self._minute_hits.setdefault(guardian_id, deque())
            d_q = self._day_hits.setdefault(guardian_id, deque())
            while m_q and ts - m_q[0] >= 60.0:
                m_q.popleft()
            while d_q and ts - d_q[0] >= 86400.0:
                d_q.popleft()
            if len(m_q) >= self.per_minute or len(d_q) >= self.per_day:
                raise MentorRateLimitExceeded("mentor_rate_limited")
            m_q.append(ts)
            d_q.append(ts)

    def reset(self) -> None:
        with self._lock:
            self._minute_hits.clear()
            self._day_hits.clear()


mentor_rate_limiter = MentorRateLimiter()


class MentorExplainCandidate(BaseModel):
    """Validated candidate returned by `MentorExplainModelPort`."""

    model_config = ConfigDict(extra="ignore")
    act: MentorAct
    topic_relation: Literal["same", "new"] | None = None
    content: str = Field(min_length=1, max_length=MENTOR_CONTENT_MAX_LENGTH)
    pronounce: PronouncePayload | None = None
    visual: Visual | None = None
    visual_dropped: str | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        act = data.get("act")
        if act != "pronounce":
            data.pop("pronounce", None)
        elif not isinstance(data.get("pronounce"), dict) and isinstance(data.get("lessons"), list):
            data["pronounce"] = {"lessons": data["lessons"]}
        elif not isinstance(data.get("pronounce"), dict) and isinstance(data.get("lesson"), dict):
            data["pronounce"] = {"lesson": data["lesson"]}
        data.pop("visual_dropped", None)
        raw_visual = data.pop("visual", None)
        if raw_visual not in (None, "", {}, []):
            if act not in {"explain", "answer"}:
                data["visual_dropped"] = "visual_not_applicable"
            else:
                try:
                    data["visual"] = VISUAL_ADAPTER.validate_python(raw_visual)
                except ValidationError as err:
                    data["visual_dropped"] = drop_reason(err)
        return data

    @property
    def lessons(self) -> list[LessonBody]:
        return list(self.pronounce.lessons) if self.pronounce else []


class MentorExplainModelPort(Protocol):
    def explain(
        self,
        *,
        content: str,
        verified_solution: VerifiedSolution | None,
        recent_utterances: list[dict],
        current_images: list[str | None],
        repair_error: str | None = None,
    ) -> dict: ...


class QwenMentorExplainGateway(MentorExplainModelPort):
    """Invokes `tutoring.mentor-explain` when present in the active Admin snapshot,
    or falls back to the pinned `tutoring.turn` model connection via `components`."""

    def __init__(self, settings_obj=None):
        self._settings = settings_obj

    def explain(
        self,
        *,
        content: str,
        verified_solution: VerifiedSolution | None,
        recent_utterances: list[dict],
        current_images: list[str | None],
        repair_error: str | None = None,
    ) -> dict:
        from app.agent_specs.contexts import build_context, guardian_mentor_explain
        from app.agent_specs.definitions import load_definitions
        from app.bootstrap.settings import settings
        from app.infrastructure.ai import components

        payload: dict[str, Any] = {
            "contract": "guardian-mentor.v1",
            "guardian_question": content,
            "topic_relation_instruction": "有历史时请用 topic_relation 标明本轮延续当前题（same）或提出新题（new）。",
            "verified_solution": verified_solution.mentor_projection()
            if verified_solution is not None
            else None,
        }
        if repair_error:
            payload["repair_error"] = repair_error

        defs = load_definitions()
        if MENTOR_EXPLAIN_ID in defs.units:
            spec = components.COMPONENTS.get(MENTOR_EXPLAIN_ID)
            user = build_context(
                MENTOR_EXPLAIN_ID,
                payload=payload,
                recent_utterances=recent_utterances,
                current_images=current_images,
            )
            return components.invoke_agent_component(
                spec=spec, user=user, settings_obj=self._settings
            ).unwrap()

        # Backward-compatible execution on existing Admin releases prior to `--guardian-mentor` import:
        # strictly uses the pinned `tutoring.turn` model configuration through `components`.
        runtime_settings = self._settings or settings
        base_spec = components.COMPONENTS.get("tutoring.turn")
        if self._settings is None and base_spec.requires_agent_switch:
            if not runtime_settings.agent_model_enabled:
                raise ModelGatewayError("model_provider_disabled")
            if not runtime_settings.dashscope_api_key:
                raise ModelGatewayError("model_provider_not_configured")

        model_name, _ = components.resolve_model(base_spec)
        user_parts = guardian_mentor_explain(
            payload=payload,
            recent_utterances=recent_utterances,
            current_images=current_images,
        )
        if not base_spec.accepts_images:
            user_parts = components._without_images(user_parts)

        telemetry: dict[str, Any] = {}
        try:
            completion = components.complete_json_chat(
                timeout=max(base_spec.timeout_seconds or 45, 60),
                model=model_name,
                temperature=0.2,
                max_tokens=max(base_spec.max_tokens, 4096),
                messages=[
                    {"role": "system", "content": DEFAULT_MENTOR_PROMPT},
                    {"role": "user", "content": user_parts},
                ],
                enable_thinking=base_spec.enable_thinking,
                thinking_budget=base_spec.thinking_budget,
                telemetry=telemetry,
            )
            parsed, outcome, abrupt_detail = components.validate_json_completion(
                completion,
                unit_id=MENTOR_EXPLAIN_ID,
            )
            components._record_call_evidence(
                {
                    "component_id": MENTOR_EXPLAIN_ID,
                    "operation": MENTOR_EXPLAIN_ID,
                    "model": model_name,
                    "provider_request_id": completion.provider_request_id,
                    "finish_reason": completion.finish_reason,
                    "stream_completed": completion.stream_completed,
                    "tokens_in": completion.tokens_in,
                    "tokens_out": completion.tokens_out,
                    "tokens_answer": completion.tokens_answer,
                    "tokens_reasoning": completion.tokens_reasoning,
                    "outcome": outcome,
                    "abrupt_detail": abrupt_detail,
                }
            )
            return parsed
        except ModelTimeBudgetExceeded:
            raise
        except (APIError, TimeoutError) as error:
            remaining_model_time()
            raise ModelGatewayError("model_transport_error") from error
        except components._CompletionClassifiedError as error:
            components._record_call_evidence(
                {
                    "component_id": MENTOR_EXPLAIN_ID,
                    "operation": MENTOR_EXPLAIN_ID,
                    "model": model_name,
                    "provider_request_id": telemetry.get("provider_request_id"),
                    "finish_reason": telemetry.get("finish_reason"),
                    "stream_completed": bool(telemetry.get("stream_completed")),
                    "tokens_in": telemetry.get("tokens_in"),
                    "tokens_out": telemetry.get("tokens_out"),
                    "tokens_answer": telemetry.get("tokens_answer"),
                    "tokens_reasoning": telemetry.get("tokens_reasoning"),
                    "outcome": error.outcome,
                    "abrupt_detail": None,
                }
            )
            raise ModelGatewayError(error.gateway_code) from error

    def review(
        self, *, question: str, solution: VerifiedSolution | None,
        candidate: MentorExplainCandidate, images: list[str],
    ) -> bool:
        """Independent read of the actual user-visible draft against the original evidence."""
        from app.agent_specs.contexts import guardian_mentor_explain
        from app.bootstrap.settings import settings
        from app.infrastructure.ai import components

        config = self._settings or settings
        if not config.agent_model_enabled or not config.dashscope_api_key:
            return False
        spec = components.COMPONENTS.get("tutoring.leak-judge")
        model, _ = components.resolve_model(spec)
        payload = {
            "question": question,
            "solution": solution.mentor_projection() if solution else None,
            "draft": candidate.content,
            "visual": candidate.visual.model_dump(mode="json") if candidate.visual else None,
        }
        operation = "guardian.mentor-review"
        started = time.monotonic()
        with components.model_call_span(operation=operation, model=model, agent_type="tutoring",
                                        enable_thinking=False) as telemetry:
            outcome = "api_error"
            try:
                completion = components.complete_json_chat(
                    model=model, timeout=spec.timeout_seconds or 30, temperature=0, max_tokens=400,
                    messages=[
                        {"role": "system", "content": MENTOR_REVIEW_PROMPT},
                        {"role": "user", "content": guardian_mentor_explain(payload=payload, current_images=images)},
                    ],
                    telemetry=telemetry,
                )
                for key in ("provider_request_id", "finish_reason", "stream_completed", "tokens_in",
                            "tokens_out", "tokens_answer", "tokens_reasoning"):
                    telemetry[key] = getattr(completion, key)
                remaining_model_time()
                parsed, _, _ = components.validate_json_completion(completion)
                if type(parsed.get("consistent")) is not bool:
                    outcome = "contract_error"
                    return False
                accepted = parsed["consistent"]
                outcome = "review_accepted" if accepted else "review_rejected"
                return accepted
            except components._CompletionClassifiedError as error:
                outcome = error.outcome
                return False
            except ModelTimeBudgetExceeded:
                outcome = "budget_exhausted"
                raise
            except (ModelGatewayError, APIError, TimeoutError):
                try:
                    remaining_model_time()
                except ModelTimeBudgetExceeded:
                    outcome = "budget_exhausted"
                    raise
                return False
            finally:
                telemetry["outcome"] = outcome
                if outcome not in {"review_accepted", "review_rejected"}:
                    telemetry["result"] = "error"
                meta = {key: telemetry.get(key) for key in (
                    "provider_request_id", "finish_reason", "stream_completed",
                    "tokens_in", "tokens_out", "tokens_answer", "tokens_reasoning",
                )}
                meta.update(operation=operation, model=model, outcome=outcome,
                            duration_ms=round((time.monotonic() - started) * 1000))
                components._record_call_evidence({"component_id": operation, **meta})
                components.record_model_response(agent_type="tutoring", content=outcome, **meta)



def _resolve_math_engine():
    from app.bootstrap.math_engine import math_engine

    env = os.environ.get("APP_ENV", "").strip().lower()
    mode = os.environ.get("MATH_ENGINE_MODE", "").strip().lower()
    sock = os.environ.get("MATH_ENGINE_SOCKET", "/run/math/engine.sock")
    if env in {"production", "prod"} or mode == "subprocess" or Path(sock).exists():
        return math_engine()
    return SubprocessMathEngineAdapter()


def _check_pronounce(lessons: list[LessonBody]) -> str | None:
    if not lessons:
        return "pronounce_without_lesson"
    for lesson in lessons:
        chunks = [lesson.source_text, lesson.introduction, lesson.reading_guide]
        for note in lesson.notes:
            chunks.extend([note.explanation, note.segment or ""])
        if any(forbidden_text(chunk) for chunk in chunks):
            return "lesson_markup"
        source = normalized(lesson.source_text)
        if any(note.segment and normalized(note.segment) not in source for note in lesson.notes):
            return "segment_not_in_source"
    return None


def _apply_confidence_honesty_gate(content: str, solution: VerifiedSolution | None) -> str:
    """Code gate: never disguise low-confidence, failed, or disputed-stem results as verified certainty."""
    if solution is None:
        return _LOW_CONFIDENCE_PREFIX + content
    if solution.tier == "T0":
        return content
    if solution.stem.needs_student_confirmation:
        return _CONDITION_CONFIRM_PREFIX + content
    if solution.confidence == "low":
        return _LOW_CONFIDENCE_PREFIX + content
    return content


def _solve_for_mentor(
    *,
    content: str,
    images: list[str],
    solver: ProblemSolverModelPort,
    bank_lookup: Callable[..., ProblemDossier | None] | None,
    workflow_spec=None,
    allow_language_direct=False,
) -> VerifiedSolution | None:
    if type(solver) is QwenProblemSolverGateway:
        from app.agent_specs.definitions import load_definitions
        from app.agent_specs.gaokao_contracts import PLANNER_ID

        if PLANNER_ID not in load_definitions().units:
            img_tag = f" [images:{len(images)}]" if images and not content.strip() else ""
            fallback_stem = StructuredStem(subject="general", raw_text=(content.strip() + img_tag)[:4000])
            if bank_lookup is not None and not images:
                bank_hit = bank_lookup(stem=fallback_stem)
                if bank_hit is not None and bank_hit.scope == "bank" and bank_hit.status == "ready":
                    return VerifiedSolution.from_dossier(bank_hit)
            return None

    from app.agent_specs.blueprint_steps import EXTRACT
    from app.agent_specs.definitions import load_definitions
    if EXTRACT in load_definitions().units:
        from app.application.commands.problem_solving import execute_blueprint
        img_tag = f" [images:{len(images)}]" if images and not content.strip() else ""
        return execute_blueprint(
            stem=StructuredStem(subject="general", raw_text=(content.strip() + img_tag)[:4000]),
            question=content, images=images, solver=solver, math_engine=_resolve_math_engine(),
            bank_lookup=bank_lookup, workflow_spec=workflow_spec, allow_language_direct=allow_language_direct,
        )

    extracted = solver.extract_stem(text=content, images=images, independent_reread=False)
    if isinstance(extracted, dict):
        if not images and content.strip():
            extracted = {**extracted, "raw_text": content.strip()}
        if extracted.get("tier") == "T0" and not extracted.get("needs_student_confirmation"):
            return VerifiedSolution(
                stem=StructuredStem.from_dict(extracted),
                tier="T0",
                status="ready",
                confidence="medium",
            )
        stem = StructuredStem.from_dict(extracted)
    else:
        img_tag = f" [images:{len(images)}]" if images and not content.strip() else ""
        stem = StructuredStem(subject="general", raw_text=(content.strip() + img_tag)[:4000])

    if bank_lookup is not None and (not images or isinstance(extracted, dict)):
        bank_hit = bank_lookup(stem=stem)
        if bank_hit is not None and bank_hit.scope == "bank" and bank_hit.status == "ready":
            return VerifiedSolution.from_dossier(bank_hit)

    tier = extracted.get("tier") if isinstance(extracted, dict) else None
    engine = _resolve_math_engine()
    return solve_and_verify_problem(
        stem=stem,
        images=images,
        solver=solver,
        math_engine=engine,
        initial_tier="T2" if tier == "T2" else "T1",
        allow_t2_escalation=bool(images) and tier is None,
    )


def _mentor_answer(guardian_id, candidate, verified_solution, safety):
    review_required = candidate is not None and candidate.act in {"explain", "answer"} and (
        verified_solution is None or verified_solution.tier != "T0" or candidate.act == "explain"
    )
    if candidate is None:
        answer = {
            "content": FALLBACK_TEXT,
            "act": "unavailable",
            "mode": "guardian_explain",
        }
    elif candidate.act == "pronounce":
        lesson_err = _check_pronounce(candidate.lessons)
        if lesson_err is not None:
            answer = {
                "content": fallback_text(lesson_err),
                "act": "unavailable",
                "mode": "guardian_explain",
            }
        else:
            review_txt = candidate.content + json.dumps(
                [ls.model_dump() for ls in candidate.lessons], ensure_ascii=False
            )
            if safety.blocks_output(text=review_txt):
                answer = {"content": SAFE_TEXT, "act": "safety", "mode": "guardian_explain"}
            else:
                answer = {
                    "content": candidate.content,
                    "act": "pronounce",
                    "mode": "guardian_explain",
                    "lessons": [
                        {
                            **ls.model_dump(),
                            "supported_rates": [0.5, 0.75, 1.0],
                            "speech_ref": seal(guardian_id, "speech", ls.model_dump()),
                        }
                        for ls in candidate.lessons
                    ],
                }
    else:
        final_text = (
            _apply_confidence_honesty_gate(candidate.content, verified_solution)
            if review_required and (verified_solution is not None or candidate.act == "explain")
            else candidate.content
        )
        review_txt = final_text + (describe(candidate.visual) if candidate.visual else "")
        if candidate.act == "safety" or safety.blocks_output(text=review_txt):
            answer = {"content": SAFE_TEXT, "act": "safety", "mode": "guardian_explain"}
        else:
            answer = {
                "content": final_text,
                "act": candidate.act,
                "mode": "guardian_explain",
            }
            if candidate.visual is not None:
                answer["visual"] = candidate.visual.model_dump(mode="json")
            if review_required and verified_solution is not None:
                answer["verification"] = {
                    "draft_reviewed": False,
                    "status": verified_solution.status,
                    "confidence": verified_solution.confidence,
                    "tier": verified_solution.tier,
                    "needs_condition_confirmation": verified_solution.stem.needs_student_confirmation,
                }

    return answer


def _render_distance_formula(content: str, slot: str, latex: str) -> str:
    delimiters = (("$$", "$$"), (r"\[", r"\]"), (r"\(", r"\)"), ("$", "$"))
    segments = []
    while slot in content:
        before, _, content = content.partition(slot)
        wrapped = any(before.endswith(start) and content.startswith(end) for start, end in delimiters)
        segments.extend((before, latex if wrapped else f"${latex}$"))
    return "".join([*segments, content])


def _distance_summary(verified_solution: VerifiedSolution, evidence: dict, unresolved: list[dict]) -> list[str]:
    from app.contexts.problem_solving.domain.distance_evidence import part_key

    formulas = evidence.get("formulas", [])
    excluded = {part_key(row["part"]) for row in [*formulas, *unresolved]}
    lines = [f"- {row['part']}：${row['latex']}$" for row in formulas]
    lines.extend(
        f"- {part}：{value}" for part, value in verified_solution.final_answers.items()
        if part_key(part).isdecimal() and part_key(part) not in excluded
    )
    return lines


def explain_for_guardian(
    *,
    guardian_id: str,
    content: str,
    attachment_keys: list[str],
    window: list[dict],
    images: list[str | None],
    rows: list[dict],
    origin: dict | None = None,
    handoff: bool = False,
    bank_lookup: Callable[..., ProblemDossier | None] | None = None,
    model_settings=None,
) -> dict:
    """Process Manager executing one stateless Guardian mentor-explanation turn."""
    from app.agent_specs.blueprint_steps import EXTRACT
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.definitions import load_definitions
    from app.agent_specs.runtime import execute_workflow

    catalog = load_catalog()
    spec = catalog.specs.get(MENTOR_WORKFLOW_ID)
    parent = spec is not None and spec.entry == MENTOR_PREPARE
    attempt_limit = spec.limits["model_calls"] if parent else 2
    safety = LocalSafetyScreening()
    prepared = None
    answer = None
    candidate = None
    verified_solution = None
    repair_error = None
    attempts = 0
    gateway = None

    def prepare(state):
        nonlocal answer, prepared
        if safety.blocks_input(text=content):
            answer = {"content": SAFE_TEXT, "act": "safety", "mode": "guardian_explain"}
        else:
            mentor_rate_limiter.check_and_record(guardian_id)
            prepared = prepare_images(window, images, content=content)
            if prepared.target.ambiguous:
                answer = {
                    "content": "这次图片没有读取成功或指向不明确，请重新拍照或说明要看哪一张。",
                    "act": "clarify", "mode": "guardian_explain",
                }
        state["branch"] = "solve" if answer is None else "deliver"
        return {"branch": state["branch"]}

    def solve(state):
        nonlocal verified_solution
        clean_window, target_images = prepared.window, prepared.images
        valid_images = [img for row in clean_window for img in row.get("image_urls", []) if img]
        valid_images.extend(img for img in target_images if img)
        question = content
        if clean_window:
            question = json.dumps({
                "current_request": content,
                "history": [{"role": row["author"], "text": row["text"]} for row in clean_window],
                "instruction": "结合相关上下文还原当前所问题面和补充条件。以本轮指定的题为准，历史作答不是已知条件。",
            }, ensure_ascii=False)
        child = catalog.spec(spec.node(MENTOR_BLUEPRINT).ref) if parent else None
        scoped = (
            child is not None and bool(valid_images) and not clean_window
            and any(edge.condition == "mentor_language" for edge in child.edges)
        )
        extractor = load_definitions().units.get(EXTRACT)
        distance_enabled = bool(valid_images and extractor and extractor.models[0].guardian_distance_evidence)
        solver_options = {}
        if scoped:
            solver_options["guardian_request"] = content
        if distance_enabled:
            solver_options["guardian_distance_evidence"] = True
        solver = QwenProblemSolverGateway(model_settings, **solver_options)
        verified_solution = _solve_for_mentor(
            content=question, images=valid_images, solver=solver,
            bank_lookup=bank_lookup, workflow_spec=child, allow_language_direct=scoped,
        )
        return {
            "status": verified_solution.status if verified_solution else "unavailable",
            **({"distance_evidence": verified_solution.stem.distance_evidence}
               if verified_solution and verified_solution.stem.distance_evidence else {}),
        }

    def explain(state):
        nonlocal attempts, gateway, repair_error, candidate
        attempts += 1
        evidence = verified_solution.stem.distance_evidence if verified_solution else None
        unresolved = evidence.get("unresolved_parts", []) if evidence else []
        if unresolved:
            pending = "、".join(dict.fromkeys(row["part"] for row in unresolved))
            blocked_figures = list(dict.fromkeys(
                row["figure"] for row in unresolved if row["reason"] == "image_unclear" and row.get("figure")
            ))
            lines = _distance_summary(verified_solution, evidence, unresolved)
            notice = f"这些小问的图上标注尚未核对：{pending}。"
            if blocked_figures:
                notice += f"请补拍{'、'.join(blocked_figures)}，让标注线两端和点名清楚可见。"
            if lines:
                candidate = MentorExplainCandidate(act="explain", content="\n".join([*lines, "", notice]))
            elif blocked_figures:
                candidate = MentorExplainCandidate(act="clarify", content=notice)
            else:
                state["branch"] = "deliver"
                return {"attempt": attempts, "branch": "deliver", "reason": "distance_evidence_unavailable"}
            state["branch"] = "deliver"
            return {"attempt": attempts, "branch": "deliver", "reason": "distance_partial_delivery"}
        if gateway is None:
            gateway = QwenMentorExplainGateway(model_settings)
        prior_error, repair_error = repair_error, None
        started = time.monotonic()
        try:
            raw = gateway.explain(
                content=content, verified_solution=verified_solution,
                recent_utterances=prepared.window, current_images=prepared.images, repair_error=prior_error,
            )
            candidate = MentorExplainCandidate.model_validate(raw)
            if (evidence and evidence["status"] == "unclear" and candidate.act == "clarify"
                    and not verified_solution.stem.needs_student_confirmation):
                candidate = None
            if evidence and evidence["status"] == "read" and candidate.act in {"explain", "answer"}:
                formulas = evidence["formulas"]
                missing = [row["slot"] for row in formulas if row["slot"] not in candidate.content]
                if missing:
                    repair_error = "只修正受影响小问的公式占位。下列标记各原样保留一次：" + "、".join(missing)
                    candidate = None
                else:
                    rendered = candidate.content
                    for row in formulas:
                        rendered = _render_distance_formula(rendered, row["slot"], row["latex"])
                    candidate = candidate.model_copy(update={"content": rendered})
        except ValidationError as err:
            repair_error = f"JSON schema validation failed: {err.errors(include_input=False)[:3]}"
        except ModelGatewayError as err:
            if str(err) == "invalid_model_candidate":
                repair_error = (
                    "上一轮输出的 JSON 不合法或因篇幅过长被截断。"
                    "请精简推导与排版，控制在 3500 字内并确保 JSON 严格完整闭合；"
                    "多小问题优先保证已确定的小问完整交付。"
                )
        has_formulas = bool(evidence and evidence.get("formulas"))
        retry = bool(repair_error and attempts < attempt_limit)
        if retry and has_formulas:
            remaining = remaining_model_time()
            retry = remaining is None or remaining > time.monotonic() - started
        state["branch"] = "retry" if retry else "deliver"
        if candidate is None and (repair_error or prior_error) and has_formulas and not retry:
            summary = "\n".join(_distance_summary(verified_solution, evidence, []))
            candidate = MentorExplainCandidate(act="explain", content=f"当前可交付的公式与小问答案：\n{summary}\n完整推导暂未完成。")
        return {"attempt": attempts, "branch": state["branch"]}

    def finish(state):
        nonlocal answer
        if answer is None:
            answer = _mentor_answer(guardian_id, candidate, verified_solution, safety)
        return {"act": answer["act"]}

    if parent:
        execute_workflow(
            spec,
            handlers={MENTOR_PREPARE: prepare, MENTOR_BLUEPRINT: solve,
                      MENTOR_EXPLAIN_ID: explain, MENTOR_FINISH: finish},
            conditions={branch: (lambda state, expected=branch: state["branch"] == expected)
                        for branch in MENTOR_PARENT_BRANCHES},
        )
    else:
        # Published snapshots predating the parent graph keep their direct delivery protocol.
        state = {}
        prepare(state)
        if state["branch"] == "solve":
            solve(state)
            explain(state)
            if state["branch"] == "retry":
                explain(state)
        finish(state)

    relation = candidate.topic_relation if candidate and answer["act"] not in {"safety", "unavailable"} else None
    turn_id = str(uuid4())
    utterance = {"turn_id": turn_id, "author": "ward", "text": content, "attachment_refs": attachment_keys}
    if not handoff and relation == "new":
        rows, origin = [], utterance
    elif attachment_keys:
        origin = utterance
    elif not handoff and relation != "same":
        # Without a confirmed continuation, rely on the bounded conversation window.
        origin = None
    next_rows = [
        *rows, utterance,
        {"turn_id": turn_id, "author": "companion", "text": answer["content"]},
    ]
    next_rows, _ = select_recent_utterances(next_rows, exclude_turn_id=None)
    answer["state_token"] = seal(guardian_id, MENTOR_PURPOSE, {
        "window": next_rows, "origin": origin, "pinned_topic": origin is not None,
    })
    return answer
