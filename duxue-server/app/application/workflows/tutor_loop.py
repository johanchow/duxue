"""tutor-turn.v4 的模型循环与出口检查，不依赖数据库。

生产的 TutoringWorkflow 与离线评测（``evals/``）共用这里的代码：评测看到的
fallback 与线上完全同源，不另抄一份规则。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.application.workflows.tutor_shape import lint_shape
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
from app.application.workflows.tutor_visual import Visual, describe
from app.contexts.study.domain.execution import ANSWER_LEAK_MARKERS
from app.contexts.tutoring.domain.tutor_permit import TutorPermit
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.observability.telemetry import (
    record_llm_fallback,
    record_tutor_candidate_rejection,
    record_tutor_shape_lint,
    record_tutor_visual_dropped,
)

INVALID_CANDIDATE = "invalid_model_candidate"


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
    visual: Visual | None = None
    visual_dropped: str | None = None
    shape_flags: list[str] = field(default_factory=list)


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
                repair = "返回的内容不是有效 JSON 对象；只返回一个符合 tutor-turn.v4 的 JSON 对象。"
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


def _check_visual_leak(leak_judge: LeakJudgePort, text: str, task_title, problem_summary) -> bool | None:
    """图泄露判官。任何异常都按"判不准"处理：图判不准只丢图，不影响文字。"""
    judge = getattr(leak_judge, "visual_leaks", None)
    if judge is None:
        return None
    try:
        return judge(text=text, task_title=task_title, problem_summary=problem_summary)
    except Exception:  # noqa: BLE001 - a broken judge must never become a shown diagram.
        return None


# 判官只在回复本身像“一个单独的事实”时才被告知 depth：长回复不可能只是一个事实，
# 即使模型声明 atomic/recall 也按原标准审，避免用标签包装一段完整讲解。
FACT_REPLY_MAX_CHARS = 200
# 判官看到本答疑会话最近这么多道题：`relation=new` 放弃的题不受保护，但孩子随后追问它的答案时，
# 判官必须还能认出来。
JUDGE_RECENT_PROBLEMS = 3


def judge_problem_summary(recent_problems: list[str], student_said: str) -> str | None:
    """泄露判官的 ``problem``：最近几道题（新的在前）加孩子本轮的话。生产与评测共用。"""
    problems = [item.strip() for item in recent_problems if item and item.strip()][:JUDGE_RECENT_PROBLEMS]
    lines = [f"第{index}题：{item}" for index, item in enumerate(problems, start=1)]
    if student_said.strip() and student_said.strip() not in problems:
        lines.append(f"孩子本轮说：{student_said.strip()}")
    return "\n".join(lines) or None


def _fact_depth(candidate: TutorTurnCandidate) -> str | None:
    """`answer` 里的单个事实：作业里的 atomic/recall，或非作业的一次性查询（`topic=atomic_lookup`）。

    只有 `answer` 才可能是"直接给一个事实"；`guide` 自称 atomic 是标签矛盾，按原标准审。"""
    if candidate.act != "answer" or len(candidate.content) > FACT_REPLY_MAX_CHARS:
        return None
    if candidate.depth in {"atomic", "recall"}:
        return candidate.depth
    if candidate.topic == "atomic_lookup":
        return "atomic"
    return None


def vet_candidate(
    candidate: TutorTurnCandidate, *, permit: TutorPermit, leak_judge: LeakJudgePort,
    task_title: str | None, problem_summary: str | None,
) -> Vetting:
    """检查 2（越权与一致性）和检查 3（泄露）。

    文字（``content``，澄清时连同候选）任一不过，调用方回退固定话术。图（``visual``）单独判断：
    不适用、非法、含答案标记、被图判官判为泄露（含超时、结果非法）一律只丢图，文字照常。
    """
    verdict = check_authority(candidate, permit)
    if not verdict.ok:
        record_llm_fallback(operation="tutor_turn", reason=verdict.reason)
        return Vetting(candidate, verdict, verdict.reason)

    flags = lint_shape(candidate.act, candidate.content)
    if candidate.act == "answer" and candidate.depth == "reasoning":
        # 提示词要求推理题用 guide；不拒绝（泄露检查照跑），只留观测。
        flags.append("answer_on_reasoning")
    if flags:
        record_tutor_shape_lint(act=candidate.act, flags=flags)

    visual, dropped = candidate.visual, candidate.visual_dropped
    visual_text = describe(visual) if visual is not None else None
    if visual_text is not None and verdict.answer_protected and any(
        marker in visual_text for marker in ANSWER_LEAK_MARKERS
    ):
        visual, visual_text, dropped = None, None, "visual_answer_marker"

    text_leaks: bool | None = False
    if verdict.needs_leak_check:
        reply = candidate.shown_text
        depth = _fact_depth(candidate)
        if visual_text is None:
            text_leaks = leak_judge.leaks(
                text=reply, task_title=task_title, problem_summary=problem_summary, depth=depth,
            )
        else:
            # 文字判官与图判官互不依赖，并行发出，只有"作业成果轮次且带图"才多这一次调用。
            with ThreadPoolExecutor(max_workers=2) as pool:
                text_future = pool.submit(
                    leak_judge.leaks, text=reply, task_title=task_title, problem_summary=problem_summary,
                    depth=depth,
                )
                visual_future = pool.submit(
                    _check_visual_leak, leak_judge, visual_text, task_title, problem_summary,
                )
                text_leaks = text_future.result()
                visual_leaks = visual_future.result()
            if text_leaks is False and visual_leaks is not False:
                visual = None
                dropped = "visual_leak_check_failed" if visual_leaks is None else "visual_leak_detected"
    if text_leaks is not False:  # True 泄露；None 判定失败，同样 fail-closed
        reason = "leak_check_failed" if text_leaks is None else "leak_detected"
        record_llm_fallback(operation="tutor_turn", reason=reason)
        return Vetting(candidate, None, reason, shape_flags=flags)
    if dropped:
        record_tutor_visual_dropped(reason=dropped)
    return Vetting(candidate, verdict, visual=visual, visual_dropped=dropped, shape_flags=flags)
