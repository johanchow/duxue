"""tutor-turn.v1 的模型循环与出口检查，不依赖数据库。

生产的 TutoringWorkflow 与离线评测（``evals/``）共用这里的代码：评测看到的
fallback 与线上完全同源，不另抄一份规则。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from app.application.workflows.tutor_tools import (
    MAX_MODEL_CALLS,
    MAX_TOOL_CALLS,
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
from app.contexts.tutoring.domain.tutor_permit import TutorPermit
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.observability.telemetry import (
    record_llm_fallback,
    record_tutor_candidate_rejection,
)

INVALID_CANDIDATE = "invalid_model_candidate"


@dataclass(frozen=True)
class ModelCall:
    """主调用的结果：候选，或没有候选的原因（只含类别，不含儿童内容）。"""

    candidate: TutorTurnCandidate | None
    failure: str | None = None


@dataclass(frozen=True)
class Vetting:
    """出口检查的结果。``failure`` 为空表示候选可以投影给 Ward。"""

    candidate: TutorTurnCandidate
    verdict: Verdict | None
    failure: str | None = None


def call_tutor_model(
    model: TutorModelPort, envelope: dict, instruction: str, window: list[dict],
    images: list, tools: TutorToolbox,
) -> ModelCall:
    """有界循环：模型要工具就执行，直到返回候选。

    至多 MAX_TOOL_CALLS 次工具、MAX_MODEL_CALLS 次主调用（含结构重试）。
    """
    repair: str | None = None
    observations: list[dict] = []
    tool_calls = 0
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
                repair = "返回的内容不是有效 JSON 对象；只返回一个符合 tutor-turn.v1 的 JSON 对象。"
                continue
            record_llm_fallback(operation="tutor_turn", reason=str(error))
            return ModelCall(None, str(error))
        except Exception as error:  # noqa: BLE001 - provider failures must fall back safely.
            record_llm_fallback(operation="tutor_turn", reason=str(error))
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
            return ModelCall(TutorTurnCandidate.model_validate(raw))
        except (ValidationError, ValueError) as error:
            error_type, field = schema_error_diagnostic(error)
            record_tutor_candidate_rejection(
                error_type=error_type, field=field, retrying=repair is None,
            )
            if repair is not None:  # 结构错误只重试一次
                break
            repair = format_schema_error(error)
    record_llm_fallback(operation="tutor_turn", reason=INVALID_CANDIDATE)
    return ModelCall(None, INVALID_CANDIDATE)


def vet_candidate(
    candidate: TutorTurnCandidate, *, permit: TutorPermit, has_open_problem: bool,
    authorized_refs: frozenset[str], has_work_input: bool, leak_judge: LeakJudgePort,
    task_title: str | None, problem_summary: str | None,
) -> Vetting:
    """检查 2（越权与一致性）和检查 3（泄露）。任一不过，调用方回退固定话术。"""
    # A clarification says the referenced source is not yet confirmed.
    # Its accompanying lesson must never be projected, but the safe
    # clarification itself is still useful to the Ward.
    if candidate.act == "clarify" and candidate.lesson is not None:
        candidate = candidate.model_copy(update={"lesson": None})
    verdict = check_authority(
        candidate, permit, has_open_problem=has_open_problem,
        authorized_history_refs=authorized_refs, has_work_input=has_work_input,
    )
    if not verdict.ok:
        record_llm_fallback(operation="tutor_turn", reason=verdict.reason)
        return Vetting(candidate, verdict, verdict.reason)
    if verdict.needs_leak_check:
        judged = leak_judge.leaks(
            text=f"{candidate.content}\n{candidate.follow_up_question or ''}",
            task_title=task_title, problem_summary=problem_summary,
        )
        if judged is not False:  # True 泄露；None 判定失败，同样 fail-closed
            reason = "leak_check_failed" if judged is None else "leak_detected"
            record_llm_fallback(operation="tutor_turn", reason=reason)
            return Vetting(candidate, None, reason)
    return Vetting(candidate, verdict)
