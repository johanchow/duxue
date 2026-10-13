"""tutor-turn.v4 的模型循环与出口检查，不依赖数据库。

生产的 TutoringWorkflow 与离线评测（``evals/``）共用这里的代码：评测看到的
fallback 与线上完全同源，不另抄一份规则。
"""

from __future__ import annotations

import re
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
    record_tutor_fact_gate,
    record_tutor_leak_retry,
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
    images: list, tools: TutorToolbox, *, repair_error: str | None = None,
) -> ModelCall:
    """有界循环：模型要工具就执行，直到返回候选。

    至多 MAX_TOOL_CALLS 次工具、MAX_MODEL_CALLS 次主调用（含结构重试）。
    ``repair_error`` 预置时（泄露后的重试）本身就是那一次重试，结构再错不另行重试。
    不记录 fallback：一轮是否回退由 ``run_tutor_turn`` 按最终结果判断。
    """
    repair: str | None = repair_error
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
            return ModelCall(None, str(error))
        except Exception as error:  # noqa: BLE001 - provider failures must fall back safely.
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


# 单个事实的确定性放行上限（字）。超过就不可能"只是一个事实"，交判官按严格标准审。
FACT_REPLY_MAX_CHARS = 120
# 判官看到本答疑会话最近这么多道题：`relation=new` 放弃的题不受保护，但孩子随后追问它的答案时，
# 判官必须还能认出来。
JUDGE_RECENT_PROBLEMS = 3
# 文字给出了答案时重试一次，请模型改成最小提示；判官自身失败不重试（重试也只会再问一次判官）。
LEAK_RETRY_REASONS = frozenset({"answer_marker", "leak_detected"})
LEAK_REPAIR = "泄露：上一版回复给出了这道作业的答案，孩子不能看到。"

# 模型最常把这几类推理结果谎称成"记住的事实"（见评测 depth-adversarial）。
# 命中任一条就不放行；宁可多问一次判官，不可误放。
_FACT_BLOCKERS = (
    ("digit", re.compile(r"[0-9０-９]")),
    ("math", re.compile(r"[=＝+＋×÷*＊<>＜＞≤≥≈%％]")),
    ("option", re.compile(r"(?<![A-Za-z])[A-D](?![A-Za-z])|选项|选择")),
    ("judgement", re.compile(r"[√✓✗✔✘]|正确|错误|不对|对的|错的|是对|是错")),
    ("inference", re.compile(r"所以|因此|因为|可得|得出|推出|算出|等于|结果")),
)


def judge_problem_summary(recent_problems: list[str], student_said: str) -> str | None:
    """泄露判官的 ``problem``：最近几道题（新的在前）加孩子本轮的话。生产与评测共用。"""
    problems = [item.strip() for item in recent_problems if item and item.strip()][:JUDGE_RECENT_PROBLEMS]
    lines = [f"第{index}题：{item}" for index, item in enumerate(problems, start=1)]
    if student_said.strip() and student_said.strip() not in problems:
        lines.append(f"孩子本轮说：{student_said.strip()}")
    return "\n".join(lines) or None


def fact_gate(candidate: TutorTurnCandidate) -> str | None:
    """单个事实的确定性放行。返回 None 表示放行（不问文字判官），否则返回不放行的原因。

    放行要同时满足：`answer`；模型声明单个事实（work 的 atomic/recall，或 non_work 的
    atomic_lookup）；正文很短；且不像计算结果、选项、对错或推理结论。标签只是必要条件，
    代码规则才是放行依据；答案标记检查在此之前已经照跑。"""
    if candidate.act != "answer":
        return "not_answer"
    if candidate.depth not in {"atomic", "recall"} and candidate.topic != "atomic_lookup":
        return "not_fact"
    if len(candidate.content) > FACT_REPLY_MAX_CHARS:
        return "too_long"
    for reason, pattern in _FACT_BLOCKERS:
        if pattern.search(candidate.content):
            return reason
    return None


def vet_candidate(
    candidate: TutorTurnCandidate, *, permit: TutorPermit, leak_judge: LeakJudgePort,
    task_title: str | None, problem_summary: str | None,
) -> Vetting:
    """检查 2（越权与一致性）和检查 3（泄露）。只判断，不记录 fallback（由 ``run_tutor_turn`` 按最终结果记）。

    文字（``content``，澄清时连同候选）任一不过，调用方回退固定话术。单个事实由 ``fact_gate``
    确定性放行，其余交判官按严格标准审。图（``visual``）单独判断：不适用、非法、含答案标记、
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
    if visual_text is not None and verdict.answer_protected and any(
        marker in visual_text for marker in ANSWER_LEAK_MARKERS
    ):
        visual, visual_text, dropped = None, None, "visual_answer_marker"

    text_leaks: bool | None = False
    visual_leaks: bool | None = False
    if verdict.needs_leak_check:
        gate = fact_gate(candidate)
        if candidate.act == "answer":
            record_tutor_fact_gate(outcome=gate or "passed")
        judge_text = gate is not None
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
            text_leaks = jobs["text"].result() if "text" in jobs else False
            visual_leaks = jobs["visual"].result() if "visual" in jobs else False
        if text_leaks is False and visual_leaks is not False:
            visual = None
            dropped = "visual_leak_check_failed" if visual_leaks is None else "visual_leak_detected"
    if text_leaks is not False:  # True 泄露；None 判定失败，同样 fail-closed
        reason = "leak_check_failed" if text_leaks is None else "leak_detected"
        return Vetting(candidate, None, reason, shape_flags=flags)
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
        retried = True
        record_tutor_leak_retry(reason=vetting.failure)
        retry = call_tutor_model(
            model, envelope, instruction, window, images, tools, repair_error=LEAK_REPAIR,
        )
        if retry.candidate is not None:
            call, vetting = retry, vet(retry.candidate)
    if vetting.failure is not None:
        record_llm_fallback(operation="tutor_turn", reason=vetting.failure)
    return TurnResult(call, vetting, retried)
