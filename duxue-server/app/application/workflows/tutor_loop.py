"""tutor-turn.v4 的模型循环与出口检查，不依赖数据库。

生产的 TutoringWorkflow 与离线评测（``evals/``）共用这里的代码：评测看到的
fallback 与线上完全同源，不另抄一份规则。
"""

from __future__ import annotations

import json
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
    agent_step_span,
    record_llm_fallback,
    record_tutor_candidate_rejection,
    record_tutor_fact_gate,
    record_tutor_leak_retry,
    record_tutor_shape_lint,
    record_tutor_visual_dropped,
    set_observation_payload,
)

INVALID_CANDIDATE = "invalid_model_candidate"
_VISUAL_REPAIR_DRAFT_MAX = 4000


def _ensure_widget_guidelines(observations: list[dict]) -> None:
    if any(item.get("tool") == "widget_guidelines" for item in observations):
        return
    with agent_step_span("tool", "widget_guidelines", **{"agent.tool.source": "preloaded"}) as span:
        set_observation_payload(span, input={})
        observations.append({
            "tool": "widget_guidelines", "status": "unique", "guidelines": SVG_WIDGET_GUIDELINES,
        })
        set_observation_payload(span, output=observations[-1])
        span.set_attribute("agent.tool.status", "unique")


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
        except Exception as error:  # noqa: BLE001 - provider boundary uses the safe fallback
            if best_candidate is not None:
                return ModelCall(best_candidate)
            return ModelCall(None, str(error))
        if isinstance(raw, dict) and "tool" in raw:
            name = str(raw.get("tool"))
            if tool_calls >= MAX_TOOL_CALLS:
                with agent_step_span("check", "tutoring.tool_budget") as span:
                    set_observation_payload(span, input={"tool": name, "calls": tool_calls, "limit": MAX_TOOL_CALLS})
                    span.set_attribute("agent.check.result", "budget_exhausted")
                    observations.append({"tool": name, "status": "budget_exhausted"})
                    set_observation_payload(span, output={"result": "budget_exhausted"})
            else:
                tool_calls += 1
                observations.append(tools.run(name, raw.get("args")))
            continue
        try:
            with agent_step_span("check", "tutoring.candidate_schema") as span:
                set_observation_payload(span, input=raw)
                try:
                    candidate = TutorTurnCandidate.model_validate(raw)
                except (ValidationError, ValueError) as error:
                    span.set_attribute("agent.check.result", "rejected")
                    error_type, field = schema_error_diagnostic(error)
                    set_observation_payload(span, output={
                        "result": "rejected", "error_type": error_type,
                        "field": field, "reason": format_schema_error(error),
                    })
                    raise
                span.set_attribute("agent.check.result", "accepted")
                set_observation_payload(span, output={"result": "accepted"})
        except (ValidationError, ValueError) as error:
            error_type, field = schema_error_diagnostic(error)
            record_tutor_candidate_rejection(
                error_type=error_type, field=field, retrying=repair is None,
            )
            if repair is not None:  # 结构错误只重试一次
                break
            repair = format_schema_error(error)
            continue
        with agent_step_span("check", "tutoring.visual_schema") as visual_span:
            set_observation_payload(visual_span, input={"visual": raw.get("visual")})
            visual_result = (
                "invalid" if candidate.visual_dropped == "visual_invalid"
                else "pass" if candidate.visual else "absent"
            )
            visual_span.set_attribute(
                "agent.check.result",
                visual_result,
            )
            if candidate.visual is not None:
                visual_span.set_attribute("tutor.visual.kind", candidate.visual.kind)
            set_observation_payload(visual_span, output={
                "result": visual_result, "reason": candidate.visual_error,
            })
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
    with agent_step_span("check", "tutoring.visual_leak") as span:
        set_observation_payload(span, input={
            "visual": text, "task_title": task_title, "problem": problem_summary,
        })
        try:
            result = judge(text=text, task_title=task_title, problem_summary=problem_summary)
        except Exception:  # noqa: BLE001 - unavailable optional judge drops the visual
            result = None
        span.set_attribute("agent.check.result", "unknown" if result is None else "leak" if result else "pass")
        set_observation_payload(span, output={"leaks": result})
        return result


def _check_text_leak(leak_judge: LeakJudgePort, text: str, task_title, problem_summary, judge_images: list[str]):
    with agent_step_span("check", "tutoring.text_leak") as span:
        set_observation_payload(span, input={
            "reply": text, "task_title": task_title, "problem": problem_summary,
            # Keep image bytes out of trace payloads. The model call itself uses the
            # shared telemetry scrubber for its multimodal message.
            "judge_image_count": len(judge_images),
        })
        result = leak_judge.leaks(
            text=text, task_title=task_title, problem_summary=problem_summary, images=judge_images,
        )
        leaks, reason = _text_leak_result(result)
        span.set_attribute("agent.check.result", "unknown" if leaks is None else "leak" if leaks else "pass")
        if reason:
            span.set_attribute("tutor.leak.reason", reason)
        set_observation_payload(span, output={"leaks": leaks, "reason": reason})
        return result


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
    task_title: str | None, problem_summary: str | None, judge_images: list[str] | None = None,
) -> Vetting:
    """Run the configured authority, text and optional visual Gates."""
    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.runtime import GateDecision, execute_workflow

    def authority(state: dict) -> GateDecision:
        with agent_step_span("check", "tutoring.authority") as span:
            verdict = check_authority(candidate, permit)
            state["authority"] = verdict
            span.set_attribute("agent.check.result", "pass" if verdict.ok else "rejected")
            set_observation_payload(span, output={"ok": verdict.ok, "reason": verdict.reason})
        if verdict.ok:
            flags = lint_shape(candidate.act, candidate.content)
            if candidate.act == "answer" and candidate.depth == "reasoning":
                flags.append("answer_on_reasoning")
            if flags:
                record_tutor_shape_lint(act=candidate.act, flags=flags)
            state["flags"] = flags
        return GateDecision("allow" if verdict.ok else "deny", verdict.reason or "ok")

    def text_leak(state: dict) -> GateDecision:
        record_tutor_fact_gate(outcome=fact_gate(candidate) or "short_fact_reviewed")
        try:
            result = _check_text_leak(
                leak_judge, candidate.shown_text, task_title, problem_summary, list(judge_images or []),
            )
        except Exception:  # noqa: BLE001 - a judge failure must reject the candidate
            result = None
        state["text_leaks"], state["leak_reason"] = _text_leak_result(result)
        return GateDecision(
            "allow" if state["text_leaks"] is False else "deny",
            "ok" if state["text_leaks"] is False else
            "leak_check_failed" if state["text_leaks"] is None else "leak_detected",
        )

    def visual_leak(state: dict) -> GateDecision:
        result = _check_visual_leak(leak_judge, state["visual_text"], task_title, problem_summary)
        if result is not False:
            state["visual"] = None
            state["dropped"] = "visual_leak_check_failed" if result is None else "visual_leak_detected"
        return GateDecision("allow" if result is False else "deny", "ok" if result is False else state["dropped"])

    def complete(state: dict) -> Vetting:
        verdict = state["authority"]
        if not verdict.ok:
            return Vetting(candidate, verdict, verdict.reason)
        if state.get("text_leaks") is not False:
            reason = "leak_check_failed" if state.get("text_leaks") is None else "leak_detected"
            return Vetting(candidate, None, reason, leak_reason=state.get("leak_reason"), shape_flags=state["flags"])
        if state["dropped"]:
            record_tutor_visual_dropped(reason=state["dropped"])
        return Vetting(
            candidate, verdict, visual=state["visual"], visual_dropped=state["dropped"],
            shape_flags=state["flags"],
        )

    conditions = {
        "always": lambda state: True,
        "authority_denied": lambda state: not state["authority"].ok,
        "authority_allowed_needs_leak_check": lambda state: state["authority"].ok and state["authority"].needs_leak_check,
        "authority_allowed_no_leak_check": lambda state: state["authority"].ok and not state["authority"].needs_leak_check,
        "text_denied": lambda state: state.get("text_leaks") is not False,
        "text_allowed_with_visual": lambda state: state.get("text_leaks") is False and state["visual_text"] is not None,
        "text_allowed_no_visual": lambda state: state.get("text_leaks") is False and state["visual_text"] is None,
        "requires_text_leak": lambda state: state["authority"].ok and state["authority"].needs_leak_check,
        "requires_visual_leak": lambda state: (
            state["authority"].ok and state["authority"].needs_leak_check
            and state.get("text_leaks") is False and state["visual_text"] is not None
        ),
    }
    state = execute_workflow(
        load_catalog().spec("tutoring-vet"),
        handlers={
            "tutoring.authority": authority,
            "tutoring.leak-judge": text_leak,
            "tutoring.visual-leak-judge": visual_leak,
            "tutoring.complete_vetting": complete,
        },
        conditions=conditions,
        initial_state={
            "visual": candidate.visual,
            "visual_text": describe(candidate.visual) if candidate.visual is not None else None,
            "dropped": candidate.visual_dropped,
            "text_leaks": False,
        },
    )
    return state["results"]["tutoring-vet.complete"]


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
    judge_images: list[str] | None = None,
) -> TurnResult:
    """主调用 + 出口检查；文字给出了答案时带 ``LEAK_REPAIR`` 重试一次，重试结果重新完整检查。

    生产与离线评测共用。``model_fallback`` 只按最终结果记录一次。"""
    def vet(candidate: TutorTurnCandidate) -> Vetting:
        with agent_step_span("check", "tutoring.exit_gate") as span:
            set_observation_payload(span, input={
                "candidate": candidate.model_dump(mode="json"), "permit": permit.as_context(),
                "task_title": task_title, "problem_summary": problem_summary,
            })
            result = vet_candidate(
                candidate, permit=permit, leak_judge=leak_judge,
                task_title=task_title, problem_summary=problem_summary, judge_images=judge_images,
            )
            span.set_attribute("agent.check.result", "rejected" if result.failure else "pass")
            if result.failure:
                span.set_attribute("tutor.failure", result.failure)
            if result.leak_reason:
                span.set_attribute("tutor.leak.reason", result.leak_reason)
            set_observation_payload(span, output={
                "failure": result.failure, "leak_reason": result.leak_reason,
                "visual_dropped": result.visual_dropped,
                "shape_flags": result.shape_flags,
            })
            if result.visual is not None:
                span.set_attribute("tutor.visual.kind", result.visual.kind)
            if result.visual_dropped:
                span.set_attribute("tutor.visual.dropped", result.visual_dropped)
            return result

    def attempt(
        current_model: TutorModelPort, kind: str, *, repair_error: str | None = None,
        preload_svg_guidelines: bool = False,
    ) -> tuple[ModelCall, Vetting | None]:
        with agent_step_span("node", "tutoring.attempt", **{"tutor.attempt.kind": kind}) as span:
            proposal = call_tutor_model(
                current_model, envelope, instruction, window, images, tools,
                repair_error=repair_error, preload_svg_guidelines=preload_svg_guidelines,
            )
            review = vet(proposal.candidate) if proposal.candidate is not None else None
            set_observation_payload(span, output={
                "candidate_available": proposal.candidate is not None,
                "failure": review.failure if review is not None else proposal.failure,
                "leak_reason": review.leak_reason if review is not None else None,
            })
            return proposal, review

    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.runtime import execute_workflow

    def primary(state):
        state["call"], state["vetting"] = attempt(model, "primary")

    def repair(state):
        review = state["vetting"]
        state["original_failure"], state["original_reason"] = review.failure, review.leak_reason
        state["retried"] = True
        record_tutor_leak_retry(reason=review.failure)
        proposal, checked = attempt(model, "repair", repair_error=_leak_repair(review))
        if checked is not None:
            state["call"], state["vetting"] = proposal, checked

    def backup(state):
        proposal, checked = attempt(backup_model, "backup", repair_error=_leak_repair(state["vetting"]))
        if checked is not None:
            state["call"], state["vetting"] = proposal, checked

    def redraw(state):
        review = state["vetting"]
        proposal, checked = attempt(model, "visual_redraw", repair_error=_visual_leak_repair(review))
        if (checked is not None and checked.failure is None and checked.visual is not None
                and checked.candidate.act == review.candidate.act
                and checked.candidate.content == review.candidate.content
                and checked.candidate.turn == review.candidate.turn):
            state["call"], state["vetting"] = proposal, checked

    def missing(state, current_model):
        proposal, checked = attempt(
            current_model, "missing_visual_redraw", repair_error=state["missing_repair"],
            preload_svg_guidelines=True,
        )
        state["missing_fixed"] = bool(
            checked is not None and checked.failure is None and checked.visual is not None
            and checked.visual.kind == "svg" and _TEXT_DIAGRAM_TEX not in checked.candidate.content
        )
        if state["missing_fixed"]:
            state["call"], state["vetting"] = proposal, checked

    def missing_decision(state):
        if state["vetting"] is not None:
            state["missing_repair"] = _missing_visual_repair(state["vetting"])

    def finish(state):
        call, review = state["call"], state["vetting"]
        failure = review.failure if review is not None else call.failure or INVALID_CANDIDATE
        if failure:
            record_llm_fallback(operation="tutor_turn", reason=failure)
        return TurnResult(call, review, state["retried"])

    def same_leak(state):
        review = state["vetting"]
        return (backup_model is not None and review.failure == state["original_failure"] == "leak_detected"
                and review.leak_reason == state["original_reason"])

    def needs_redraw(state):
        review = state["vetting"]
        return review.failure is None and review.visual_dropped == "visual_leak_detected"

    def needs_missing(state):
        review = state["vetting"]
        return review.failure is None and review.visual is None and _TEXT_DIAGRAM_TEX in review.candidate.content

    state = execute_workflow(
        load_catalog().spec("tutoring-retry"), initial_state={"retried": False},
        handlers={
            "primary": primary, "repair": repair, "backup": backup,
            "visual_decision": lambda state: None, "visual_redraw": redraw,
            "missing_decision": missing_decision,
            "missing_primary": lambda state: missing(state, model),
            "missing_backup": lambda state: missing(state, backup_model), "finish": finish,
        },
        conditions={
            "no_candidate": lambda state: state["call"].candidate is None,
            "retry_leak": lambda state: state["vetting"] is not None and state["vetting"].failure in LEAK_RETRY_REASONS,
            "candidate_without_retry": lambda state: state["vetting"] is not None and state["vetting"].failure not in LEAK_RETRY_REASONS,
            "same_leak_with_backup": same_leak, "no_backup_needed": lambda state: not same_leak(state),
            "needs_visual_redraw": needs_redraw, "no_visual_redraw": lambda state: not needs_redraw(state),
            "needs_missing_visual": needs_missing, "no_missing_visual": lambda state: not needs_missing(state),
            "retry_missing_with_backup": lambda state: not state["missing_fixed"] and backup_model is not None,
            "missing_attempt_done": lambda state: state["missing_fixed"] or backup_model is None,
        },
    )
    return state["results"]["tutoring-retry.finish"]
