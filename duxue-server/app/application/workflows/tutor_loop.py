"""tutor-turn.v4 的模型循环与出口检查，不依赖数据库。

生产的 TutoringWorkflow 与离线评测（``evals/``）共用这里的代码：评测看到的
fallback 与线上完全同源，不另抄一份规则。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

from pydantic import ValidationError

from app.agent_specs.catalog import load_catalog
from app.agent_specs.execution_trace import transition
from app.agent_specs.static_tools import static_tool_result
from app.agent_specs.subworkflows import (
    MATH_NODE,
    RETRY_NODE,
    VET_MATH_NODE,
    VET_NODE,
    has_parallel_vet,
    math_review_step,
)
from app.application.workflows.tutor_shape import lint_shape
from app.application.workflows.tutor_tools import (
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
from app.application.workflows.tutor_visual import (
    DeliveredVisual,
    SearchPhoto,
    describe,
)
from app.contexts.tutoring.domain.tutor_permit import TutorPermit
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.prompts import render_fragment
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
    from app.agent_specs.definitions import load_definitions
    if "tutoring.widget_guidelines" not in load_definitions().units["tutoring.turn"].tools:
        return
    if any(item.get("tool") == "widget_guidelines" for item in observations):
        return
    with agent_step_span("tool", "widget_guidelines", **{"agent.tool.source": "preloaded"}) as span:
        set_observation_payload(span, input={})
        observations.append({
            "tool": "widget_guidelines", **static_tool_result("tutoring.widget_guidelines"),
        })
        set_observation_payload(span, output=observations[-1])
        span.set_attribute("agent.tool.status", "unique")


def _visual_repair(candidate: TutorTurnCandidate, raw: dict, *, reason: str | None = None) -> str:
    draft = {key: raw[key] for key in ("act", "content", "turn", "visual") if key in raw}
    rejected = json.dumps(draft, ensure_ascii=False)
    if len(rejected) > _VISUAL_REPAIR_DRAFT_MAX:
        rejected = rejected[:_VISUAL_REPAIR_DRAFT_MAX] + "…"
    return render_fragment("tutoring.turn", "visual_schema",
                           reason=reason or candidate.visual_error, draft=rejected)


@dataclass(frozen=True)
class ModelCall:
    """主调用的结果：候选，或没有候选的原因（只含类别，不含儿童内容）。"""

    candidate: TutorTurnCandidate | None
    failure: str | None = None
    used_calls: int = 0


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
    visual: DeliveredVisual | None = None
    visual_dropped: str | None = None
    shape_flags: list[str] = field(default_factory=list)
    visual_need: str | None = None
    visual_feedback: str | None = None


def call_tutor_model(
    model: TutorModelPort, envelope: dict, instruction: str, window: list[dict],
    images: list, tools: TutorToolbox, *, repair_error: str | None = None,
    preload_svg_guidelines: bool = False, review_evidence=None, call_budget: int | None = None,
) -> ModelCall:
    """有界循环：模型要工具就执行，直到返回候选。

    工具与主调用次数上限来自本轮固定的 Workflow 配置（含结构重试）。
    ``repair_error`` 预置时（泄露后的重试）本身就是那一次重试，结构再错不另行重试。
    不记录 fallback：一轮是否回退由 ``run_tutor_turn`` 按最终结果判断。
    """
    repair: str | None = repair_error
    ledger = getattr(tools, "math_verification", None)
    observations: list[dict] = ([{"tool": "math", **record} for record in ledger.records.values()]
                                if ledger is not None else [])
    if review_evidence is not None:
        observations.append({"kind": "verified_image_review", "image_review": review_evidence.model_dump(mode="json")})
        envelope = {**envelope, "image_review_phase": "response"}
        try:
            source, _ = json.JSONDecoder().raw_decode(instruction)
            instruction = json.dumps({key: source[key] for key in ('student_said', 'permit', 'expected_act') if key in source}, ensure_ascii=False)
        except (ValueError, TypeError):
            pass

    if preload_svg_guidelines:
        _ensure_widget_guidelines(observations)
    tool_calls = 0
    best_candidate: TutorTurnCandidate | None = None
    limits = load_catalog().spec("tutoring").limits
    max_model_calls, max_tool_calls = limits["model_calls"], limits["tool_calls"]
    call_limit = min(max_model_calls, call_budget) if call_budget is not None else max_model_calls
    used_calls = 0

    def result(candidate, failure=None):
        return ModelCall(candidate, failure, used_calls)

    for _ in range(call_limit):
        used_calls += 1
        call_envelope = dict(envelope)
        if getattr(tools, "inspected_crops", None) and review_evidence is None:
            call_envelope["inspected_crops"] = list(tools.inspected_crops)
        try:
            raw = model.complete(
                envelope=call_envelope, instruction=instruction,
                recent_utterances=[] if review_evidence is not None else window,
                current_images=[] if review_evidence is not None else images,
                repair_error=repair, observations=observations,
            )
        except ModelGatewayError as error:
            # json.loads() lives in the provider adapter.  An empty string
            # or malformed JSON gets here before Pydantic can issue its
            # usual repair request, but it deserves the same one retry.
            if str(error) == "invalid_model_candidate" and repair is None:
                record_tutor_candidate_rejection(
                    error_type="invalid_json", field="root", retrying=used_calls < call_limit,
                )
                repair = render_fragment("tutoring.turn", "invalid_json")
                continue
            if best_candidate is not None:
                return result(best_candidate)
            return result(None, str(error))
        except Exception as error:  # noqa: BLE001 - provider boundary uses the safe fallback
            if best_candidate is not None:
                return result(best_candidate)
            return result(None, str(error))
        if isinstance(raw, dict) and "tool" in raw:
            name = str(raw.get("tool"))
            if tool_calls >= max_tool_calls:
                with agent_step_span("check", "tutoring.tool_budget") as span:
                    set_observation_payload(span, input={"tool": name, "calls": tool_calls, "limit": max_tool_calls})
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
                    if raw.get("photo_ref") is not None:
                        if candidate.act not in {"guide", "answer"} or raw.get("visual"):
                            raise ValueError("photo requires an answer or guide without another visual")
                        photo = SearchPhoto.from_result(raw.get("photo_caption"), tools.web_search.photo(raw["photo_ref"]))
                        candidate = candidate.model_copy(update={"visual": photo})
                    if review_evidence is not None:
                        candidate = candidate.model_copy(update={"image_review": review_evidence})
                    elif candidate.image_review is not None and ledger is None:
                        from app.application.workflows.image_review import (
                            reconcile_calculations,
                        )
                        candidate = candidate.model_copy(update={
                            'image_review': reconcile_calculations(candidate.image_review),
                        })
                    from app.application.workflows.image_review import (
                        validate_image_review,
                    )
                    ledger = getattr(tools, "math_verification", None)
                    if ledger is not None:
                        candidate = ledger.reconcile_image(candidate)
                        ledger.validate(candidate.math_claims)
                    elif candidate.math_claims:
                        raise ValueError("math_evidence_unavailable")
                    validate_image_review(candidate, [
                        *(url for row in window for url in row.get("image_urls", [])), *images,
                    ], external_calculations=ledger is not None)
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
            from app.application.workflows.image_review import ImageReviewProtocolError
            record_tutor_candidate_rejection(
                error_type=error_type, field=field,
                retrying=used_calls < call_limit and (repair is None or isinstance(error, ImageReviewProtocolError)),
            )
            if isinstance(error, ImageReviewProtocolError):
                repair = error.feedback()
                continue  # Still consumes the configured model-call budget.
            if repair is not None:  # Other structural errors retain one retry.
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
                "visual_error": "svg generated without widget_guidelines", "rejected_svg": True,
            })
            if repair is not None:
                return result(best_candidate)
            _ensure_widget_guidelines(observations)
            repair = _visual_repair(candidate, raw, reason=render_fragment("tutoring.turn", "widget_not_loaded"))
            continue
        if best_candidate is not None and (
            candidate.act != best_candidate.act
            or candidate.content != best_candidate.content
            or candidate.turn != best_candidate.turn
        ):
            return result(best_candidate)
        return result(candidate)
    if best_candidate is not None:
        return result(best_candidate)
    return result(None, INVALID_CANDIDATE)


def _check_visual_leak(leak_judge: LeakJudgePort, text: str, task_title, problem_summary, *, photo=None) -> bool | None:
    """图泄露判官。任何异常都按"判不准"处理：图判不准只丢图，不影响文字。"""
    judge = getattr(leak_judge, "visual_leaks", None)
    if judge is None:
        return None
    with agent_step_span("check", "tutoring.visual_leak") as span:
        set_observation_payload(span, input={
            "visual": text, "task_title": task_title, "problem": problem_summary,
        })
        try:
            result = judge(text=text, task_title=task_title, problem_summary=problem_summary,
                           **({"image": photo.judge_image()} if photo else {}))
        except Exception:  # noqa: BLE001 - unavailable optional judge drops the visual
            result = None
        span.set_attribute("agent.check.result", "unknown" if result is None else "leak" if result else "pass")
        set_observation_payload(span, output={"leaks": result})
        return result


def _check_text_leak(leak_judge: LeakJudgePort, text: str, task_title, problem_summary, judge_images: list[str], *, phase="response"):
    with agent_step_span("check", "tutoring.text_leak", **{"image.review.phase": phase}) as span:
        set_observation_payload(span, input={
            "reply": text, "task_title": task_title, "problem": problem_summary, "review_phase": phase,
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
# 越过作业答案边界或数学核验不一致时重试一次；判官自身失败不重试。
LEAK_RETRY_REASONS = frozenset({"leak_detected", "math_inconsistent"})
def __getattr__(name):
    if name == "LEAK_REPAIR":
        return render_fragment("tutoring.turn", "leak_prefix")
    raise AttributeError(name)

_TEXT_DIAGRAM_TEX = r"\enclose{longdiv}"


def judge_problem_summary(
    recent_problems: list[str], student_said: str, *, recent_utterances: list[dict] | None = None,
    verified_final_answers: dict[str, str] | None = None,
) -> str | None:
    """审核题目及有界学生证据；导师原话不当作学生已经提交的答案。

    防误杀红线：绝不向裁判注入中间里程碑列表；仅当档案 ready 且 confidence=="high" 时可选提供 verified_final_answers。
    """
    problems = [item.strip() for item in recent_problems if item and item.strip()][:JUDGE_RECENT_PROBLEMS]
    ward_texts = [str(item.get("text", "")).strip() for item in (recent_utterances or [])
                  if item.get("author") == "ward" and str(item.get("text", "")).strip()]
    if not problems and not ward_texts and not student_said.strip():
        return None
    payload: dict = {
        "current_request": student_said.strip(),
        "recent_problems": problems,
        "student_evidence": [text[:300] for text in ward_texts[-JUDGE_RECENT_STUDENT_UTTERANCES:]],
    }
    if verified_final_answers:
        payload["verified_final_answers"] = dict(verified_final_answers)
    return json.dumps(payload, ensure_ascii=False)


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
    if reason == "math_inconsistent":
        return json.dumps({"kind": "math_verification_failed", "reason": reason,
                           "instruction": "依据本轮工具记录修正；缺证据先核算；未知只说明未核验"}, ensure_ascii=False)
    if reason in {"incorrect_confirmation", "premature_conclusion"}:
        return json.dumps({"kind": "verification_disagreement", "reason": reason,
                           "student_answer_correct": None}, ensure_ascii=False)
    if reason in {"final_answer", "complete_solution"}:
        return render_fragment("tutoring.turn", "leak_answer", prefix=render_fragment("tutoring.turn", "leak_prefix"), reason=reason)
    rejected = json.dumps(vetting.candidate.shown_text[:800], ensure_ascii=False)
    return render_fragment("tutoring.turn", "leak_draft", prefix=render_fragment("tutoring.turn", "leak_prefix"), reason=reason, draft=rejected)


def _visual_leak_repair(vetting: Vetting) -> str:
    rejected = json.dumps(vetting.candidate.model_dump(mode="json"), ensure_ascii=False)
    if len(rejected) > _VISUAL_REPAIR_DRAFT_MAX:
        rejected = rejected[:_VISUAL_REPAIR_DRAFT_MAX] + "…"
    return render_fragment("tutoring.turn", "visual_leak", draft=rejected)


def _missing_visual_repair(vetting: Vetting) -> str:
    payload = vetting.candidate.model_dump(mode="json")
    if vetting.visual_feedback:
        payload = {"visual_review_feedback": vetting.visual_feedback, **payload}
    draft = json.dumps(payload, ensure_ascii=False)
    if len(draft) > _VISUAL_REPAIR_DRAFT_MAX:
        draft = draft[:_VISUAL_REPAIR_DRAFT_MAX] + "…"
    return render_fragment("tutoring.turn", "missing_visual", draft=draft)


def fact_gate(candidate: TutorTurnCandidate) -> str | None:
    """短事实分类，仅用于观测；返回 None 表示模型声明了短事实。

    模型自报的 atomic/recall/atomic_lookup 不能作为跳过受保护题目审核的权限。
    分类不看关键词或数字；受保护题目统一交独立判官审核。"""
    if candidate.depth not in {"atomic", "recall"} and candidate.topic != "atomic_lookup":
        return "not_fact"
    if len(candidate.content) > FACT_REPLY_MAX_CHARS:
        return "too_long"
    return None


def _evaluate_authority(
    candidate: TutorTurnCandidate,
    *,
    permit: TutorPermit,
    judge_images: list[str] | None,
    grade_stage: str | None,
) -> tuple[Verdict, list[str]]:
    from app.agent_specs.visual_delivery import enabled as visual_delivery_enabled

    verdict = check_authority(candidate, permit)
    if verdict.ok and candidate.act in {"answer", "guide"} and visual_delivery_enabled():
        verdict = replace(verdict, needs_leak_check=True)
    if verdict.ok and isinstance(candidate.visual, SearchPhoto):
        verdict = replace(verdict, needs_leak_check=True)
    if verdict.ok and judge_images and candidate.act in {"answer", "guide", "chat"}:
        # The generator's non_work label cannot exempt image grading
        # from independent review, including in a fresh conversation.
        verdict = replace(verdict, needs_leak_check=True)
    flags: list[str] = []
    if verdict.ok:
        flags = lint_shape(candidate.act, candidate.content, grade_stage=grade_stage)
        if candidate.act == "answer" and candidate.depth == "reasoning":
            flags.append("answer_on_reasoning")
    return verdict, flags


def _prepare_vet_problem_summary(
    candidate: TutorTurnCandidate,
    problem_summary: str | None,
    judge_images: list[str] | None,
) -> str | None:
    from app.agent_specs.visual_delivery import enabled as visual_delivery_enabled
    from app.application.workflows.image_review import review_problem

    prepared = review_problem(problem_summary, candidate, list(judge_images or []))
    if visual_delivery_enabled():
        try:
            summary = json.loads(prepared) if prepared else {}
        except (ValueError, TypeError):
            summary = {"problem": prepared}
        if not isinstance(summary, dict):
            summary = {"problem": summary}
        summary["candidate_visual"] = candidate.visual.model_dump(mode="json") if candidate.visual else None
        prepared = json.dumps(summary, ensure_ascii=False)
    return prepared


def _invoke_text_leak_with_retry(
    leak_judge: LeakJudgePort,
    candidate: TutorTurnCandidate,
    task_title: str | None,
    problem_summary: str | None,
    judge_images: list[str],
):
    """Run text_leak judge with one in-place retry on transient unknown/error."""
    result = None
    for _ in range(2):
        try:
            result = _check_text_leak(
                leak_judge, candidate.shown_text, task_title, problem_summary, judge_images,
            )
        except Exception:  # noqa: BLE001 - a judge failure must reject the candidate
            result = None
        text_leaks, _ = _text_leak_result(result)
        if text_leaks is not None:
            break
    return result


def vet_candidate(
    candidate: TutorTurnCandidate, *, permit: TutorPermit, leak_judge: LeakJudgePort,
    task_title: str | None, problem_summary: str | None, judge_images: list[str] | None = None,
    grade_stage: str | None = None,
    verdict_assertion_allowed: bool = True,
    ledger=None,
    raw_problem_summary: str | None = None,
    reused_text_vetting: Vetting | None = None,
) -> Vetting:
    """Run the configured authority, math, text and optional visual Gates via tutoring-vet."""
    from app.agent_specs.runtime import GateDecision, execute_tutoring_child

    images_list = list(judge_images or [])
    effective_summary = _prepare_vet_problem_summary(candidate, problem_summary, images_list)
    visual_text_init = describe(candidate.visual) if candidate.visual is not None else None
    parallel_topology = has_parallel_vet(load_catalog())

    def authority(state: dict) -> GateDecision:
        with agent_step_span("check", "tutoring.authority") as span:
            verdict, flags = _evaluate_authority(
                candidate, permit=permit, judge_images=images_list, grade_stage=grade_stage,
            )
            state["authority"] = verdict
            state["flags"] = list(flags)
            span.set_attribute("agent.check.result", "pass" if verdict.ok else "rejected")
            set_observation_payload(span, output={"ok": verdict.ok, "reason": verdict.reason})
        if verdict.ok and flags:
            record_tutor_shape_lint(act=candidate.act, flags=flags)
        if not verdict.ok:
            return GateDecision("deny", verdict.reason or "authority_denied")

        # When running the declarative parallel tutoring-vet workflow, local math ledger validation
        # executes here before fanning out to independent LLM Judges.
        if parallel_topology and ledger is not None:
            needs_semantic_math = (
                candidate.act not in {"pronounce", "safety", "redirect"}
                or bool(candidate.math_claims)
                or bool(ledger.records)
            )
            try:
                ledger.validate(candidate.math_claims)
            except Exception:  # noqa: BLE001 - invalid local math claims short-circuit before LLM Judges
                state["local_math_failed"] = True
                return GateDecision("deny", "math_check_failed")
            state["needs_math_review"] = (
                needs_semantic_math and getattr(leak_judge, "check_math", None) is not None
            )
        else:
            state["needs_math_review"] = False

        state["needs_text_review"] = bool(verdict.needs_leak_check and reused_text_vetting is None)
        state["needs_visual_review"] = bool(verdict.needs_leak_check and visual_text_init is not None)
        return GateDecision("allow", "ok")

    def math_consistency(state: dict) -> GateDecision:
        with agent_step_span("check", MATH_NODE) as math_span:
            check = getattr(leak_judge, "check_math", None)
            checked = None
            try:
                if check is not None and ledger is not None:
                    math_ctx = {
                        "problem": raw_problem_summary if raw_problem_summary is not None else problem_summary,
                        "candidate_turn": candidate.turn.model_dump() if candidate.turn else None,
                        **ledger.context(candidate.math_claims),
                    }
                    math_text = candidate.content + ("\n" + visual_text_init if visual_text_init else "")
                    for _ in range(2):
                        checked = check(text=math_text, context=math_ctx, images=images_list)
                        if checked is not None:
                            break
            except Exception:  # noqa: BLE001 - independent math check fails closed
                checked = None
            set_observation_payload(
                math_span, output={"semantic_review": True, "math_consistent": checked},
            )
            math_span.set_attribute(
                "agent.check.result",
                "pass" if checked is True else "unknown" if checked is None else "rejected",
            )
        state["math_reviewed"] = True
        state["math_checked"] = checked
        return GateDecision(
            "allow" if checked is True else "deny",
            "ok" if checked is True else "math_check_failed" if checked is None else "math_inconsistent",
        )

    def text_leak(state: dict) -> GateDecision:
        if reused_text_vetting is not None:
            state["text_leaks"] = False
            state["leak_reason"] = None
            state["visual_need"] = reused_text_vetting.visual_need
            state["visual_feedback"] = reused_text_vetting.visual_feedback
            if reused_text_vetting.verdict is not None:
                state["turn_answer_protected"] = reused_text_vetting.verdict.answer_protected
            return GateDecision("allow", "ok")

        record_tutor_fact_gate(outcome=fact_gate(candidate) or "short_fact_reviewed")
        result = _invoke_text_leak_with_retry(
            leak_judge, candidate, task_title, effective_summary, images_list,
        )
        text_leaks, leak_reason = _text_leak_result(result)
        visual_need = None
        visual_feedback = None
        visual_not_helpful = False
        if isinstance(result, dict) and result.get("visual_need") in {"requested", "helpful", "not_needed", "uncertain"}:
            visual_need = result["visual_need"]
            if isinstance(result.get("visual_evidence"), str):
                visual_feedback = result["visual_evidence"][:500]
            if result.get("visual_adequate") is False and visual_need in {"requested", "helpful"}:
                visual_not_helpful = True
        # Code-enforced confidence gate (§4.4): when neither a ready verified dossier nor
        # direct deterministic engine verification exists on this turn, affirming the student's
        # reasoning answer by pure LLM mental math is strictly denied!
        if (
            text_leaks is False
            and not verdict_assertion_allowed
            and isinstance(result, dict)
            and result.get("affirms_student_answer") is True
            and (result.get("answer_protected") is not False)
        ):
            text_leaks = True
            leak_reason = "incorrect_confirmation"

        # Write isolated text-branch keys (safe during parallel fan-out).
        state["text_leaks"] = text_leaks
        state["leak_reason"] = leak_reason
        state["visual_need"] = visual_need
        state["visual_feedback"] = visual_feedback
        state["text_visual_not_helpful"] = visual_not_helpful
        if visual_not_helpful and not parallel_topology:
            state["visual"] = None
            state["visual_text"] = None
            state["dropped"] = "visual_not_helpful"
        if text_leaks is False and isinstance(result, dict) and type(result.get("answer_protected")) is bool:
            state["turn_answer_protected"] = result["answer_protected"]

        return GateDecision(
            "allow" if text_leaks is False else "deny",
            "ok" if text_leaks is False else
            "leak_check_failed" if text_leaks is None else "leak_detected",
        )

    def visual_leak(state: dict) -> GateDecision:
        result = _check_visual_leak(leak_judge, visual_text_init, task_title, effective_summary,
                                    photo=candidate.visual if isinstance(candidate.visual, SearchPhoto) else None)
        # Write isolated visual-branch key (safe during parallel fan-out).
        state["visual_leak_result"] = result
        if not parallel_topology and result is not False:
            state["visual"] = None
            state["dropped"] = "visual_leak_check_failed" if result is None else "visual_leak_detected"
        return GateDecision(
            "allow" if result is False else "deny",
            "ok" if result is False else ("visual_leak_check_failed" if result is None else "visual_leak_detected"),
        )

    def complete(state: dict) -> Vetting:
        verdict = state["authority"]
        if state.get("local_math_failed"):
            return Vetting(candidate, None, "math_check_failed", "math_inconsistent")
        if not verdict.ok:
            return Vetting(candidate, verdict, verdict.reason)
        # Deterministic precedence after parallel fan-in: math > text_leak > visual_leak.
        if state.get("math_reviewed") and state.get("math_checked") is not True:
            checked = state.get("math_checked")
            return Vetting(
                candidate, None,
                "math_check_failed" if checked is None else "math_inconsistent",
                "math_inconsistent",
            )
        if reused_text_vetting is not None:
            text_leaks = False
            visual_need = reused_text_vetting.visual_need
            visual_feedback = reused_text_vetting.visual_feedback
            if reused_text_vetting.verdict is not None:
                state["turn_answer_protected"] = reused_text_vetting.verdict.answer_protected
        else:
            text_leaks = state.get("text_leaks")
            visual_need = state.get("visual_need")
            visual_feedback = state.get("visual_feedback")
        if text_leaks is not False:
            reason = "leak_check_failed" if text_leaks is None else "leak_detected"
            return Vetting(candidate, None, reason, leak_reason=state.get("leak_reason"), shape_flags=state["flags"])

        visual = state["visual"]
        dropped = state["dropped"]
        if isinstance(visual, SearchPhoto) and state.get("visual_leak_result") is not False:
            visual = None
            dropped = "visual_leak_detected" if state.get("visual_leak_result") else "visual_leak_check_failed"
        elif state.get("text_visual_not_helpful"):
            visual = None
            dropped = "visual_not_helpful"
        elif "visual_leak_result" in state and state["visual_leak_result"] is not False:
            visual = None
            dropped = "visual_leak_check_failed" if state["visual_leak_result"] is None else "visual_leak_detected"
        if dropped:
            record_tutor_visual_dropped(reason=dropped)
        if "turn_answer_protected" in state:
            protected = state["turn_answer_protected"] or verdict.effective_work_product
            verdict = replace(verdict, answer_protected=protected,
                              effective_work_product=verdict.effective_work_product and protected)
        return Vetting(
            candidate, verdict, visual=visual, visual_dropped=dropped,
            shape_flags=state["flags"], visual_need=visual_need,
            visual_feedback=visual_feedback,
        )

    conditions = {
        "always": lambda state: True,
        "authority_denied": lambda state: not state["authority"].ok or bool(state.get("local_math_failed")),
        "authority_allowed_no_review": lambda state: (
            state["authority"].ok
            and not state.get("local_math_failed")
            and not state.get("needs_math_review")
            and not state.get("needs_text_review")
            and not state.get("needs_visual_review")
        ),
        "needs_math_review": lambda state: (
            state["authority"].ok and not state.get("local_math_failed") and bool(state.get("needs_math_review"))
        ),
        "needs_text_review": lambda state: (
            state["authority"].ok and not state.get("local_math_failed") and bool(state.get("needs_text_review"))
        ),
        "needs_visual_review": lambda state: (
            state["authority"].ok and not state.get("local_math_failed") and bool(state.get("needs_visual_review"))
        ),
        # Legacy serial tutoring-vet conditions (retained for backward compatibility with older snapshots)
        "authority_allowed_needs_leak_check": lambda state: state["authority"].ok and state["authority"].needs_leak_check,
        "authority_allowed_no_leak_check": lambda state: state["authority"].ok and not state["authority"].needs_leak_check,
        "text_denied": lambda state: state.get("text_leaks") is not False,
        "text_allowed_with_visual": lambda state: state.get("text_leaks") is False and state["visual_text"] is not None,
        "text_allowed_no_visual": lambda state: state.get("text_leaks") is False and state["visual_text"] is None,
        "requires_text_leak": lambda state: (
            state["authority"].ok and not state.get("local_math_failed")
            and state["authority"].needs_leak_check and reused_text_vetting is None
        ),
        "requires_visual_leak": lambda state: (
            state["authority"].ok and not state.get("local_math_failed")
            and state["authority"].needs_leak_check and visual_text_init is not None
            and (parallel_topology or (state.get("text_leaks") is False and state["visual_text"] is not None))
        ),
    }
    state = execute_tutoring_child(
        VET_NODE,
        handlers={
            "tutoring.authority": authority,
            VET_MATH_NODE: math_consistency,
            "tutoring-vet.text_leak": text_leak,
            "tutoring.leak-judge": text_leak,
            "tutoring.visual-leak-judge": visual_leak,
            "tutoring.complete_vetting": complete,
        },
        conditions=conditions,
        initial_state={
            "visual": candidate.visual,
            "visual_text": visual_text_init,
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
    if hasattr(tools, "begin_math"):
        tools.begin_math(envelope, instruction, list(judge_images or [
            *(url for row in window for url in row.get("image_urls", [])), *images,
        ]))

    def vet(candidate: TutorTurnCandidate, *, reuse_text_vetting: Vetting | None = None) -> Vetting:
        with agent_step_span("check", "tutoring.exit_gate") as span:
            set_observation_payload(span, input={
                "candidate": candidate.model_dump(mode="json"), "permit": permit.as_context(),
                "task_title": task_title, "problem_summary": problem_summary,
            })
            ledger = getattr(tools, "math_verification", None)
            images_list = list(judge_images or [])
            catalog = load_catalog()
            explicit_calls = catalog.spec("tutoring").node(RETRY_NODE).kind == "workflow"
            parallel_topology = has_parallel_vet(catalog)

            if parallel_topology:
                if explicit_calls:
                    transition("tutoring", "tutoring.exit_gate", VET_NODE)
            else:
                # Legacy serial topology (pre-upgrade snapshots): run MATH_NODE before tutoring-vet.
                if explicit_calls:
                    transition("tutoring", "tutoring.exit_gate", MATH_NODE)
                with math_review_step(explicit_calls) as math_span:
                    if math_span is not None and ledger is None:
                        set_observation_payload(math_span, output={"reviewed": False})
                    if ledger is not None:
                        needs_semantic_math = (
                            candidate.act not in {"pronounce", "safety", "redirect"}
                            or bool(candidate.math_claims)
                            or bool(ledger.records)
                        )
                        try:
                            ledger.validate(candidate.math_claims)
                            if needs_semantic_math:
                                check = getattr(leak_judge, "check_math", None)
                                checked = None
                                if check is not None:
                                    math_ctx = {
                                        "problem": problem_summary,
                                        "candidate_turn": candidate.turn.model_dump() if candidate.turn else None,
                                        **ledger.context(candidate.math_claims),
                                    }
                                    math_text = candidate.content + ("\n" + describe(candidate.visual) if candidate.visual else "")
                                    for _ in range(2):
                                        checked = check(text=math_text, context=math_ctx, images=images_list)
                                        if checked is not None:
                                            break
                            else:
                                checked = True
                        except Exception:  # noqa: BLE001 - independent math check fails closed
                            checked = None
                        if math_span is not None:
                            set_observation_payload(math_span, output={"semantic_review": needs_semantic_math, "math_consistent": checked})
                        if checked is not True:
                            return Vetting(candidate, None, "math_check_failed" if checked is None else "math_inconsistent",
                                           "math_inconsistent")
                if explicit_calls:
                    transition("tutoring", MATH_NODE, VET_NODE, "math_allowed")

            checked_summary = (
                json.dumps({"problem": problem_summary, **ledger.context(candidate.math_claims)}, ensure_ascii=False)
                if ledger is not None else problem_summary
            )
            actor_stage = (envelope.get("actor") or {}).get("grade_stage") if isinstance(envelope, dict) else None
            has_direct_engine_verdict = bool(
                ledger is not None
                and (
                    candidate.math_claims
                    or any(rec.get("status") == "ok" for rec in ledger.records.values())
                )
            )
            dossier_gate_meta = envelope.get("_dossier_gate") if isinstance(envelope, dict) else None
            if isinstance(dossier_gate_meta, dict):
                dossier_allows = bool(dossier_gate_meta.get("allows_verdict_assertion", False))
                verdict_allowed = dossier_allows or has_direct_engine_verdict
            else:
                verdict_allowed = True

            result = vet_candidate(
                candidate, permit=permit, leak_judge=leak_judge,
                task_title=task_title, problem_summary=checked_summary, judge_images=images_list,
                grade_stage=actor_stage,
                verdict_assertion_allowed=verdict_allowed,
                ledger=ledger if parallel_topology else None,
                raw_problem_summary=problem_summary,
                reused_text_vetting=reuse_text_vetting,
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
                "visual_need": result.visual_need,
                "visual_feedback": result.visual_feedback,
                "answer_protected": result.verdict.answer_protected if result.verdict else None,
            })
            if result.visual is not None:
                span.set_attribute("tutor.visual.kind", result.visual.kind)
            if result.visual_dropped:
                span.set_attribute("tutor.visual.dropped", result.visual_dropped)
            return result

    def attempt(
        current_model: TutorModelPort, kind: str, *, repair_error: str | None = None,
        preload_svg_guidelines: bool = False,
        approved_text_vetting: Vetting | None = None,
    ) -> tuple[ModelCall, Vetting | None]:
        transition("tutoring", "tutoring.model_loop" if kind == "primary" else "tutoring.exit_gate",
                   "tutoring.attempt", None if kind == "primary" else "retry")
        with agent_step_span("node", "tutoring.attempt", **{"tutor.attempt.kind": kind}) as span:
            set_observation_payload(span, input={"instruction": instruction, "window": window, "permit": permit.as_context(), "attempt_kind": kind, "repair_error": repair_error})
            proposal = call_tutor_model(
                current_model, envelope, instruction, window, images, tools,
                repair_error=repair_error, preload_svg_guidelines=preload_svg_guidelines,
            )
            if proposal.candidate is not None:
                transition("tutoring", "tutoring.attempt", "tutoring.exit_gate", "candidate")
            candidate = proposal.candidate
            if (
                approved_text_vetting is not None
                and candidate is not None
                and (
                    candidate.act != approved_text_vetting.candidate.act
                    or candidate.content != approved_text_vetting.candidate.content
                    or candidate.turn != approved_text_vetting.candidate.turn
                )
            ):
                # Redraw must keep approved act/content/turn identical; if altered, reject without calling Judges.
                set_observation_payload(span, output={
                    "candidate_available": True,
                    "used_model_calls": proposal.used_calls,
                    "failure": "redraw_changed_approved_text",
                    "leak_reason": None,
                })
                return proposal, None
            evidence = candidate.image_review if candidate is not None else None
            if judge_images and evidence is not None:
                if evidence.conclusion != "not_checking":
                    from app.application.workflows.image_review import review_problem
                    summary = json.loads(review_problem(problem_summary, candidate, list(judge_images or [])))
                    summary['image_review_phase'] = 'evidence_only'
                    ledger = getattr(tools, "math_verification", None)
                    if ledger is not None:
                        summary["math_records"] = list(ledger.records.values())
                    try:
                        evidence_result = _check_text_leak(leak_judge, '', task_title,
                                                          json.dumps(summary, ensure_ascii=False), list(judge_images or []), phase='evidence')
                        rejected, reason = _text_leak_result(evidence_result)
                    except Exception:  # noqa: BLE001 - unverified evidence never becomes a reply
                        rejected, reason = None, None
                    if rejected is not False:
                        review = Vetting(candidate, None, 'leak_check_failed' if rejected is None else 'leak_detected',
                                         reason or 'premature_conclusion')
                        set_observation_payload(span, output={"phase": "image_review_evidence", "failure": review.failure, "leak_reason": review.leak_reason})
                        return proposal, review
                    remaining = load_catalog().spec('tutoring').limits['model_calls'] - proposal.used_calls
                    polished = call_tutor_model(current_model, envelope, instruction, window, images, tools,
                                                review_evidence=evidence, call_budget=remaining)
                    proposal = ModelCall(polished.candidate, polished.failure, proposal.used_calls + polished.used_calls)
                elif candidate.content.strip() == "待核验":
                    remaining = load_catalog().spec('tutoring').limits['model_calls'] - proposal.used_calls
                    if remaining > 0:
                        polished = call_tutor_model(current_model, envelope, instruction, window, images, tools,
                                                    review_evidence=evidence, call_budget=remaining)
                        proposal = ModelCall(polished.candidate, polished.failure, proposal.used_calls + polished.used_calls)
                    else:
                        return proposal, Vetting(candidate, None, INVALID_CANDIDATE)
            review = (
                vet(proposal.candidate, reuse_text_vetting=approved_text_vetting)
                if proposal.candidate is not None
                else None
            )
            set_observation_payload(span, output={
                "candidate_available": proposal.candidate is not None,
                "used_model_calls": proposal.used_calls,
                "failure": review.failure if review is not None else proposal.failure,
                "leak_reason": review.leak_reason if review is not None else None,
            })
            return proposal, review

    from app.agent_specs.catalog import load_catalog
    from app.agent_specs.runtime import execute_tutoring_child

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
        proposal, checked = attempt(
            model,
            "visual_redraw",
            repair_error=_visual_leak_repair(review),
            approved_text_vetting=review,
        )
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
            and (state["vetting"].visual_need in {"requested", "helpful"} or checked.visual.kind == "svg")
            and _TEXT_DIAGRAM_TEX not in checked.candidate.content
        )
        if state["missing_fixed"]:
            state["call"], state["vetting"] = proposal, checked

    def missing_decision(state):
        if state["vetting"] is not None:
            state["missing_repair"] = _missing_visual_repair(state["vetting"])

    def finish(state):
        call, review = state["call"], state["vetting"]
        if review is not None and review.failure is None and review.visual is None and (
            review.visual_need in {"requested", "helpful"} or review.candidate.rejected_svg
        ):
            review = replace(review, verdict=None, failure="visual_unavailable")
        if (review and tools.web_search.image_requested and review.failure in {None, "visual_unavailable"}
                and not isinstance(review.visual, SearchPhoto)):
            review = replace(review, visual=None, verdict=None, failure="photo_unavailable")
        failure = review.failure if review is not None else call.failure or INVALID_CANDIDATE
        if failure:
            record_llm_fallback(operation="tutor_turn", reason=failure)
        return TurnResult(call, review, state["retried"])

    def same_leak(state):
        review = state["vetting"]
        return (backup_model is not None and review.leak_reason != "math_inconsistent" and review.failure == state["original_failure"] == "leak_detected"
                and review.leak_reason == state["original_reason"])

    def needs_redraw(state):
        review = state["vetting"]
        return not tools.web_search.image_requested and review.failure is None and review.visual_dropped == "visual_leak_detected"

    def needs_missing(state):
        review = state["vetting"]
        return not tools.web_search.image_requested and review.failure is None and review.visual is None and (
            review.visual_need in {"requested", "helpful"} or _TEXT_DIAGRAM_TEX in review.candidate.content
        )

    state = execute_tutoring_child(
        RETRY_NODE, initial_state={"retried": False},
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
