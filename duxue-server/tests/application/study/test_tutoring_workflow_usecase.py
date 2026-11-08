from __future__ import annotations

import json

import pytest

from app.application.ports.companion import RunInvocation
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.persistence.models import (
    CompanionCommand,
    CompanionMessage,
    ConversationThread,
    OutboxEvent,
    StudySession,
    TutoringProblem,
    TutoringSession,
    uid,
)
from tests.support.factories import create_study_session, create_task, create_ward
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

ATTEMPT = tutor_raw(
    "guide", student_move="attempt", progress="none",
    evidence="我先试着把已知条件写出来", next_subgoal="写出第一个等式",
)
KNOWLEDGE = tutor_raw(
    "answer", "diamond beach 的中文意思是钻石海滩。", relation="none", student_move="other",
)


def _events(db):
    return [e.payload.get("event_type") for e in db.query(OutboxEvent).all()]


def _ask(db, workflow, session, content="这道题怎么做", **turn):
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=session.ward_id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": content, "tutoring_directive": "ask", **turn},
    ))
    db.commit()
    return outcome


def _setup(db, title="初中代数"):
    ward = create_ward(db)
    session = create_study_session(db, ward=ward, task=create_task(db, ward=ward, title=title))
    db.commit()
    return ward, session


def _workflow(db, *raws, judge=None):
    model = StaticTutorModel(*raws)
    return TutoringWorkflow(db, turn_model=model, leak_judge=judge or StaticLeakJudge(False)), model


@pytest.mark.parametrize("reason,expected", [
    ("choice_verdict", "这次没能直接给出检查结果，是因为回答中涉及选择题或判断题的选项对错。这部分我可以陪你检查判断依据，你可以选一道题，说说你为什么这样选。"),
    ("final_answer", "这次回答会直接给出题目的最终答案，这一步需要留给你完成。我可以换成提示，你可以告诉我卡在哪一步。"),
    ("complete_solution", "这次回答会把整道题的解法直接写完，没有给你留下自己推理的步骤。我可以改为一步提示，你可以告诉我想从哪一步继续。"),
    ("incorrect_confirmation", "这次回答还没有充分依据确认你的答案是否正确，所以暂时不能给出对错结论。你可以选一道题，我们一起核对解题过程。"),
    ("premature_conclusion", "这次回答跳过了必要的计算或检查，还不能把结论当作已经验证。你可以说说已经做到哪一步，我们一起补上验证。"),
    (None, "这次暂时没能完成回答，请稍后再试。"),
])
def test_final_failure_explains_reason_without_committing_rejected_work(db, monkeypatch, reason, expected):
    from app.application.workflows import tutoring_workflow as module
    from app.application.workflows.tutor_loop import ModelCall, TurnResult, Vetting
    from app.application.workflows.tutor_turn import TutorTurnCandidate
    from app.infrastructure.persistence.models import TutoringMessage

    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    candidate = TutorTurnCandidate.model_validate(ATTEMPT)
    failure = "leak_detected" if reason else "leak_check_failed"
    result = TurnResult(ModelCall(candidate), Vetting(candidate, None, failure, leak_reason=reason))
    monkeypatch.setattr(workflow, "_run_model", lambda *args, **kwargs: result)
    recorded = []
    monkeypatch.setattr(module, "record_tutor_turn_result", lambda **kwargs: recorded.append(kwargs))
    outcome = _ask(db, workflow, session, "我已经写了答案，只想检查是不是都对了")

    assert outcome.next_interaction["content"] == expected
    assert outcome.next_interaction["model_fallback"] is True
    assert recorded[-1]["shown"] == expected
    assert db.query(TutoringMessage).filter_by(role="assistant").one().content == expected
    assert db.query(TutoringProblem).count() == 0
    assert not _events(db)


@pytest.mark.parametrize("failure,reason", [
    ("leak_check_failed", "choice_verdict"),
    ("no_candidate", "final_answer"),
    ("private_provider_exception", None),
    ("leak_detected", "unknown_reason"),
    (None, None),
])
def test_unknown_or_technical_failure_never_uses_a_teaching_boundary(failure, reason):
    from app.application.workflows.tutor_turn import FALLBACK_TEXT, fallback_text

    assert fallback_text(failure, reason) == FALLBACK_TEXT


@pytest.mark.parametrize("failure", ["pronounce_without_lesson", "lesson_markup", "segment_not_in_source"])
def test_invalid_pronunciation_offers_a_retry_without_exposing_internal_error(failure):
    from app.application.workflows.tutor_turn import fallback_text

    assert fallback_text(failure) == "这次没能生成可用的发音内容。你可以指定要读的单词或句子，再试一次。"


def test_tutoring_workflow_step_by_step_and_close(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)

    outcome1 = _ask(db, workflow, session, "我先把 y 代入第一个式子，得到 3")
    assert outcome1.run_status == "waiting_for_ward"
    assert outcome1.next_interaction["hint_index"] == 1
    assert db.query(TutoringSession).filter_by(study_session_id=session.id).one().status == "active"
    assert "tutoring.attempt_recorded" in _events(db)
    assert "tutoring.hint_given" in _events(db)

    outcome2 = _ask(db, workflow, session, "我明白了", tutoring_directive="understood")
    assert outcome2.next_interaction["status"] == "understood"
    assert "tutoring.understanding_confirmed" in _events(db)

    outcome3 = _ask(db, workflow, session, tutoring_directive="close")
    assert outcome3.run_status == "closed"
    tutor = db.query(TutoringSession).filter_by(study_session_id=session.id).one()
    assert tutor.status == "closed" and tutor.closed_at is not None
    assert "tutoring.session_closed" in _events(db)


def test_subgoal_observation_matches_the_persisted_problem(db, monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from app.infrastructure.observability import telemetry

    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", provider.get_tracer)
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)

    with telemetry.agent_turn_span():
        _ask(db, workflow, session, "我先把已知条件写出来")
        telemetry.record_tutor_subgoal_committed()

    problem = db.query(TutoringProblem).one()
    node = next(span for span in exporter.get_finished_spans()
                if span.attributes.get("agent.step") == "tutoring.apply_problem")
    assert problem.active_subgoal == "写出第一个等式"
    assert '"candidate_next_subgoal": "写出第一个等式"' in node.attributes["langfuse.observation.input"]
    assert '"active_subgoal": "写出第一个等式"' in node.attributes["langfuse.observation.output"]
    safety = next(span for span in exporter.get_finished_spans()
                  if span.attributes.get("agent.step") == "tutoring.output_safety")
    assert json.loads(safety.attributes["langfuse.observation.input"])["text"] == ATTEMPT["content"]
    assert json.loads(safety.attributes["langfuse.observation.output"]) == {"result": "pass"}
    for step in ("tutoring.turn", "tutoring.model_loop", "tutoring.result"):
        traced = next(span for span in exporter.get_finished_spans()
                      if span.attributes.get("agent.step") == step)
        assert "langfuse.observation.input" in traced.attributes
        assert "langfuse.observation.output" in traced.attributes


def test_locked_refuses_a_solution_and_writes_nothing(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw("answer", "答案是 5"), judge=StaticLeakJudge(True))
    outcome = _ask(db, workflow, session, "直接告诉我答案")
    assert outcome.next_interaction["model_fallback"] is True
    assert "答案是 5" not in outcome.next_interaction["content"]
    assert _events(db) == []
    assert db.query(TutoringProblem).count() == 0


def test_protected_image_turn_passes_only_authorized_current_image_to_leak_judge(db, monkeypatch):
    _, session = _setup(db)
    key = f"ward/{session.ward_id}/companion/homework.jpg"
    monkeypatch.setattr(
        "app.application.queries.run_transcript._default_reader",
        lambda object_key: "data:image/jpeg;base64,authorized" if object_key == key else None,
    )
    judge = StaticLeakJudge(False)
    workflow, _ = _workflow(db, ATTEMPT, judge=judge)

    _ask(db, workflow, session, "看看我图片里写的答案对不对", attachment_keys=[key])

    assert judge.images == [["data:image/jpeg;base64,authorized"]]


def test_repeated_attempts_never_unlock_the_next_round(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    second = _ask(db, workflow, session, "那是 4")
    assert second.next_interaction["problem_status"] == "open"
    assert '"answer_protected": true' in model.calls[1]["instruction"]
    _ask(db, workflow, session, "还是不会")
    assert '"answer_protected": true' in model.calls[2]["instruction"]


def test_protected_problem_never_accepts_a_revealed_solution(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "3")
    _ask(db, workflow, session, "4")
    reveal = tutor_raw("answer", "先消元得到 x=2，再代入。", student_move="request_answer")
    workflow.turn_model = StaticTutorModel(reveal)
    workflow.leak_judge = StaticLeakJudge(True)  # the content decides, not the labels
    rejected = _ask(db, workflow, session, "讲给我听")
    assert rejected.next_interaction["model_fallback"] is True


def test_a_knowledge_question_mislabelled_as_new_work_is_answered_and_opens_no_problem(db):
    """线上：「自转和公转」被标成 act=answer + relation=new，曾整轮回退，孩子只看到兜底话术。"""
    _, session = _setup(db)
    raw = tutor_raw("answer", "自转管昼夜，公转管四季。", relation="new", student_move="request_answer")
    workflow, _ = _workflow(db, raw)
    outcome = _ask(db, workflow, session, "自转和公转有什么区别")
    assert outcome.next_interaction["model_fallback"] is False
    assert outcome.next_interaction["content"].startswith("自转管昼夜")
    assert db.query(TutoringProblem).count() == 0  # the next turn is not locked by a phantom problem


def test_asking_for_the_answer_without_attempts_never_unlocks(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw("guide", student_move="request_answer"))
    for _ in range(4):
        _ask(db, workflow, session, "告诉我答案")
    problem = db.query(TutoringProblem).one()
    assert problem.status == "open" and problem.substantive_attempts == 0


def test_submitted_attempt_ends_the_problem_and_is_not_a_hint(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw(
        "guide", "你的思路是先移项再除以系数，检查一下代回去成立吗？", student_move="attempt", progress="submitted",
        evidence="先移项再除以系数，所以 x=2",
    ))
    outcome = _ask(db, workflow, session, "x=2")
    assert outcome.next_interaction["problem_status"] == "submitted"
    assert outcome.next_interaction["hint_index"] is None
    assert "tutoring.understanding_confirmed" not in _events(db)
    assert "tutoring.hint_given" not in _events(db)
    assert "tutoring.attempt_recorded" in _events(db)


def test_progress_without_evidence_is_ignored_not_rejected(db):
    """旧 confirm_without_solved：声称完成但没有证据，只是不推进题目，回答照常展示。"""
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw(
        "guide", "再想一想这一步为什么成立。", student_move="attempt", progress="submitted",
    ))
    outcome = _ask(db, workflow, session)
    assert outcome.next_interaction["model_fallback"] is False
    assert outcome.next_interaction["problem_status"] == "open"


def test_chat_reply_that_used_to_be_a_confirm_is_not_replaced_by_the_fallback(db):
    """Live incident: the child answered the model's own choice question ("壮阔宏大")
    and the model replied with a confirmation on a chat turn.  Chat turns carry no
    work claim, so nothing there can trip the generic 没能整理出回答 fallback."""
    _, session = _setup(db)
    reply = "看来你更喜欢壮阔宏大的风格！要不要分享一句最震撼的写景诗句？"
    workflow, _ = _workflow(db, tutor_raw("chat", reply, relation=None))
    outcome = _ask(db, workflow, session, "壮阔宏大的")
    assert outcome.next_interaction["model_fallback"] is False
    assert reply in outcome.next_interaction["content"]
    assert "tutoring.curiosity_observed" not in _events(db)


def test_new_problem_starts_locked(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "3")
    _ask(db, workflow, session, "4")
    workflow.turn_model = StaticTutorModel(tutor_raw("guide", relation="new"))
    _ask(db, workflow, session, "再看另一道题")
    rows = db.query(TutoringProblem).order_by(TutoringProblem.created_at).all()
    assert [r.status for r in rows] == ["abandoned", "open"]
    assert rows[1].status == "open" and rows[1].substantive_attempts == 0


def test_replayed_turn_counts_the_attempt_once(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    invocation = RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=session.ward_id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": "我觉得是 3", "tutoring_directive": "ask"},
    )
    workflow.invoke(invocation)
    workflow.invoke(invocation)
    assert db.query(TutoringProblem).one().substantive_attempts == 1


def test_leak_check_blocks_a_locked_reply_and_fails_closed(db):
    _, session = _setup(db)
    for verdict in (True, None):
        workflow, _ = _workflow(db, tutor_raw("guide", "x 就是 2"), judge=StaticLeakJudge(verdict))
        outcome = _ask(db, workflow, session)
        assert outcome.next_interaction["model_fallback"] is True
    assert _events(db) == []


def test_knowledge_question_is_answered_directly_without_leak_check_or_problem(db):
    _, session = _setup(db, "英语阅读")
    judge = StaticLeakJudge(True)
    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(tutor_raw("answer", "这是用相机拍的。", relation="none", student_move="other")), leak_judge=judge)
    outcome = _ask(db, workflow, session, "这张图是哪个 App 拍的")
    assert judge.calls == 0
    assert db.query(TutoringProblem).count() == 0
    # 一次性查询不写好奇心事实；好奇心只来自模型明确声明的 topic
    assert "tutoring.curiosity_observed" not in _events(db)
    assert "tutoring.hint_given" not in _events(db)
    assert outcome.next_interaction["model_fallback"] is False


def test_curiosity_fact_comes_from_the_declared_topic_not_from_being_non_work(db):
    _, session = _setup(db, "英语阅读")
    raw = tutor_raw("answer", "因为太阳光被空气散射。", relation="none", topic="spontaneous_curiosity")
    workflow, _ = _workflow(db, raw)
    _ask(db, workflow, session, "天为什么是蓝的")
    assert "tutoring.curiosity_observed" in _events(db)
    assert db.query(TutoringProblem).count() == 0


def test_an_unknown_topic_is_a_lookup_and_writes_no_fact(db):
    _, session = _setup(db, "英语阅读")
    raw = tutor_raw("answer", "海滩。", relation="none")
    raw["turn"]["topic"] = "wondering"
    workflow, _ = _workflow(db, raw)
    _ask(db, workflow, session, "beach 是什么意思")
    assert "tutoring.curiosity_observed" not in _events(db)


def test_non_attempt_progress_is_ignored_instead_of_replacing_a_safe_reply(db):
    _, session = _setup(db, "英语阅读")
    raw = tutor_raw(
        "answer", "这个词表示海滩。", relation="none", student_move="request_hint", progress="some",
    )
    workflow, _ = _workflow(db, raw)
    outcome = _ask(db, workflow, session, "beach 是什么意思")
    assert outcome.next_interaction["model_fallback"] is False
    assert "海滩" in outcome.next_interaction["content"]


def test_candidate_with_omitted_safe_metadata_and_extra_field_is_accepted(db):
    _, session = _setup(db, "英语阅读")
    raw = {
        "act": "answer",
        "content": "beach 的意思是海滩。",
        "turn": {"type": "non_work"},
        "provider_debug": "unused",
    }
    workflow, model = _workflow(db, raw)
    outcome = _ask(db, workflow, session, "beach 是什么意思")
    assert len(model.calls) == 1
    assert outcome.next_interaction["model_fallback"] is False
    assert "海滩" in outcome.next_interaction["content"]


def test_open_problem_tightens_a_mislabeled_followup(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    mislabeled = tutor_raw("answer", "答案是 5", relation="same", student_move="request_answer")
    workflow.turn_model = StaticTutorModel(mislabeled)
    workflow.leak_judge = StaticLeakJudge(True)
    outcome = _ask(db, workflow, session, "那答案呢")
    assert outcome.next_interaction["model_fallback"] is True


def test_relation_none_does_not_switch_off_the_leak_check_on_an_open_problem(db):
    """模型把"这题答案是什么"标成 none，也必须过泄露裁判。"""
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    workflow.turn_model = StaticTutorModel(
        tutor_raw("answer", "把 x 单独留在左边就得到结果了。" + "再核对一遍。" * 20, relation="none"),
    )
    workflow.leak_judge = StaticLeakJudge(True)
    outcome = _ask(db, workflow, session, "那答案呢")
    assert outcome.next_interaction["model_fallback"] is True


def test_a_submitted_problem_stays_protected_until_code_releases_it(db):
    """"孩子交了"不等于允许披露：提交后追问答案仍受保护。"""
    _, session = _setup(db)
    submitted = tutor_raw(
        "guide", "你的思路我看到了。", relation="same", student_move="attempt", progress="submitted",
        evidence="先移项再除以 2，所以 x=3",
    )
    workflow, _ = _workflow(db, submitted)
    outcome = _ask(db, workflow, session, "x=3")
    assert outcome.next_interaction["problem_status"] == "submitted"
    assert outcome.next_interaction["answer_protected"] is True
    workflow.turn_model = StaticTutorModel(
        tutor_raw("answer", "先移项再除以 2 就是答案。", relation="none", topic="spontaneous_curiosity"),
    )
    workflow.leak_judge = StaticLeakJudge(True)
    assert _ask(db, workflow, session, "标准答案是什么").next_interaction["model_fallback"] is True


def test_a_single_fact_inside_homework_is_answered_directly_unless_it_is_the_answer(db):
    """A protected fact can be answered after review, without advancing the problem."""
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    problem = db.query(TutoringProblem).one()
    before = (problem.status, problem.substantive_attempts, problem.hints_given)
    fact = tutor_raw("answer", "斜边是直角三角形里最长的边。", relation="same", depth="atomic")
    workflow.turn_model = StaticTutorModel(fact)
    shown = _ask(db, workflow, session, "斜边是什么")
    assert shown.next_interaction["model_fallback"] is False and "斜边" in shown.next_interaction["content"]
    db.refresh(problem)
    assert (problem.status, problem.substantive_attempts, problem.hints_given) == before
    workflow.leak_judge = StaticLeakJudge(False)
    still_a_fact = _ask(db, workflow, session, "斜边是哪条")
    assert still_a_fact.next_interaction["model_fallback"] is False
    assert workflow.leak_judge.calls == 1
    workflow.leak_judge = StaticLeakJudge(True)
    workflow.turn_model = StaticTutorModel(tutor_raw("answer", "斜边是 5。", relation="same", depth="atomic"))
    number = _ask(db, workflow, session, "空格里填什么")
    assert number.next_interaction["model_fallback"] is True
    assert "5" not in number.next_interaction["content"]
    assert workflow.leak_judge.calls == 2  # initial reply and repair both reviewed


def test_a_task_session_gets_the_reminder_after_a_knowledge_answer(db):
    _, session = _setup(db, "英语的典范故事阅读")
    workflow, _ = _workflow(db, KNOWLEDGE)
    outcome = _ask(db, workflow, session, "diamond beach 是什么意思")
    assert "钻石海滩" in outcome.next_interaction["content"]
    assert "先回到正在进行的任务" in outcome.next_interaction["content"]


def test_structure_error_retries_once_then_falls_back(db):
    _, session = _setup(db)
    model = StaticTutorModel({"act": "guide", "content": "先说说。"})
    workflow = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge())
    outcome = _ask(db, workflow, session)
    assert len(model.calls) == 2 and model.calls[1]["repair_error"]
    assert outcome.next_interaction["model_fallback"] is True
    assert _events(db) == []


def test_invalid_json_gateway_response_retries_once_then_keeps_a_valid_reply(db):
    """空字符串等网关层 JSON 错误也应得到一次定向修复机会。"""
    _, session = _setup(db)

    class InvalidJsonThenValidModel:
        def __init__(self):
            self.calls = []

        def complete(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise ModelGatewayError("invalid_model_candidate")
            return KNOWLEDGE

    model = InvalidJsonThenValidModel()
    workflow = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge())
    outcome = _ask(db, workflow, session, "beach 是什么意思")
    assert len(model.calls) == 2
    assert model.calls[1]["repair_error"]
    assert outcome.next_interaction["model_fallback"] is False
    assert "钻石海滩" in outcome.next_interaction["content"]


def test_tutoring_without_session_opens_a_taskless_session_and_replies(db):
    ward = create_ward(db)
    db.commit()
    workflow = TutoringWorkflow(db, turn_model=StaticTutorModel(KNOWLEDGE), leak_judge=StaticLeakJudge())
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"content": "铁木真统一了蒙古的什么？", "tutoring_directive": "ask"},
    ))
    db.commit()
    assert outcome.next_interaction["content"]
    session = db.query(StudySession).filter_by(ward_id=ward.id).one()
    assert session.task_id is None and session.status == "active"
    assert "先回到正在进行的任务" not in outcome.next_interaction["content"]


def test_the_window_reaches_the_model_and_history_is_authorized(db):
    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    command = CompanionCommand(id=uid(), ward_id=ward.id, thread_id=thread.id, payload_digest="prior")
    db.add(command)
    db.flush()
    db.add(CompanionMessage(
        ward_id=ward.id, thread_id=thread.id, command_id=command.id, turn_id=uid(), attempt=1,
        thread_version=1, author_type="companion", content="1. diamond beach\n2. kling beach",
    ))
    db.commit()
    model = StaticTutorModel(tutor_raw("clarify", "你说的是上面列出的哪一句？", relation=None))
    outcome = TutoringWorkflow(db, turn_model=model, leak_judge=StaticLeakJudge()).invoke(RunInvocation(
        run_id=uid(), thread_id=thread.id, ward_id=ward.id, agent_type="tutoring",
        turn={"content": "他们都是什么意思", "tutoring_directive": "ask"},
    ))
    assert "diamond beach" in model.calls[0]["recent_utterances"][0]["text"]
    assert "diamond beach" in model.calls[0]["instruction"]  # 授权历史候选
    assert "你说的是上面列出的哪一句？" in outcome.next_interaction["content"]
    assert db.query(StudySession).count() == 0


def test_model_can_read_the_attempt_summary_through_a_tool(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    workflow.turn_model = model = StaticTutorModel(
        {"tool": "get_attempt_summary", "args": {}}, tutor_raw("guide"),
    )
    outcome = _ask(db, workflow, session, "再提示一下")
    assert len(model.calls) == 2
    seen = model.calls[1]["observations"][0]
    assert seen["tool"] == "get_attempt_summary" and seen["substantive_attempts"] == 1
    assert outcome.next_interaction["model_fallback"] is False


def test_tool_budget_and_unknown_tools_are_bounded(db):
    _, session = _setup(db)
    loop = {"tool": "get_task_context", "args": {}}
    workflow, model = _workflow(db, loop, loop, loop, {"tool": "delete_everything"}, tutor_raw())
    outcome = _ask(db, workflow, session)
    # 3 次工具后，第 4 次主调用仍要工具，预算耗尽，回退。
    assert len(model.calls) == 4
    assert outcome.next_interaction["model_fallback"] is True
    assert model.calls[3]["observations"][2]["tool"] == "get_task_context"


def test_unknown_tool_is_a_typed_error_observation(db):
    _, session = _setup(db)
    workflow, model = _workflow(db, {"tool": "delete_everything"}, tutor_raw())
    outcome = _ask(db, workflow, session)
    assert model.calls[1]["observations"][0]["status"] == "tool_error"
    assert outcome.next_interaction["model_fallback"] is False


def test_lookup_history_finds_an_earlier_ward_message(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3 因为 y 等于 1")
    workflow.turn_model = model = StaticTutorModel(
        {"tool": "lookup_history", "args": {"query": "y 等于"}}, tutor_raw("guide"),
    )
    _ask(db, workflow, session, "再提示一下")
    obs = model.calls[1]["observations"][0]
    assert obs["status"] == "unique" and obs["matches"][0]["ref"].startswith("m:")


def test_the_leak_judge_still_sees_a_problem_abandoned_by_relation_new(db):
    """relation=new 放弃了旧题；孩子随后追问旧题答案时，判官必须还能对照旧题。"""
    _, session = _setup(db)
    judge = StaticLeakJudge(False)
    workflow, _ = _workflow(db, ATTEMPT, judge=judge)
    _ask(db, workflow, session, "小明有3份小红有5份一共几份")
    workflow.turn_model = StaticTutorModel(tutor_raw("guide", "这道新题先读题。", relation="new"))
    _ask(db, workflow, session, "换一题：3x=9")
    assert [row.status for row in db.query(TutoringProblem).order_by(TutoringProblem.created_at)] == ["abandoned", "open"]
    workflow.turn_model = StaticTutorModel(
        tutor_raw("answer", "一共 8 份。", relation="none", topic="spontaneous_curiosity"),
    )
    _ask(db, workflow, session, "上一题答案是多少")
    problem = judge.problems[-1]
    assert "小明有3份小红有5份一共几份" in problem and "换一题：3x=9" in problem
    assert json.loads(problem)["current_request"] == "上一题答案是多少"


def test_an_attempt_without_evidence_records_no_attempt_fact(db):
    """事实与计数同源：没有证据的 attempt 不计实质尝试，也不发 attempt_recorded。"""
    _, session = _setup(db)
    workflow, _ = _workflow(db, tutor_raw("guide", "你是怎么想的？", student_move="attempt", progress="some"))
    _ask(db, workflow, session, "我觉得是 3")
    assert db.query(TutoringProblem).one().substantive_attempts == 0
    assert "tutoring.attempt_recorded" not in _events(db)


def test_a_replayed_attempt_turn_does_not_record_the_attempt_twice(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    turn = {"study_session_id": session.id, "content": "我觉得是 3", "tutoring_directive": "ask"}
    invocation = RunInvocation(run_id=uid(), thread_id=uid(), ward_id=session.ward_id, agent_type="tutoring", turn=turn)
    workflow.invoke(invocation)
    workflow.invoke(invocation)
    db.commit()
    assert _events(db).count("tutoring.attempt_recorded") == 1


def test_a_hint_request_with_a_stray_submitted_progress_still_counts_as_a_hint(db):
    _, session = _setup(db)
    raw = tutor_raw("guide", "先读题。", student_move="request_hint", progress="submitted", evidence="x=3")
    workflow, _ = _workflow(db, raw)
    outcome = _ask(db, workflow, session, "给点提示")
    problem = db.query(TutoringProblem).one()
    assert outcome.next_interaction["hint_index"] == 1
    assert problem.status == "open" and problem.substantive_attempts == 0


def test_a_redirect_does_not_get_a_second_reminder(db):
    _, session = _setup(db, "英语的典范故事阅读")
    workflow, _ = _workflow(db, tutor_raw("redirect", "我们先把这篇故事读完，游戏的事等会儿再聊。", relation=None))
    content = _ask(db, workflow, session, "我们来玩游戏吧").next_interaction["content"]
    assert "先回到正在进行的任务" not in content


def test_a_clarify_on_a_protected_problem_cannot_carry_the_answer(db):
    _, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我觉得是 3")
    workflow.turn_model = StaticTutorModel(tutor_raw("clarify", "你问的是哪个？", relation=None, candidates=["x 等于 2", "y 等于 1"]))
    workflow.leak_judge = StaticLeakJudge(True)
    outcome = _ask(db, workflow, session, "哪个是答案")
    assert outcome.next_interaction["model_fallback"] is True
    assert "x 等于 2" not in outcome.next_interaction["content"]


def test_a_dictation_word_can_be_answered_but_a_calculation_result_is_reviewed(db):
    """A fact remains answerable, while a mislabeled computation cannot bypass review."""
    _, session = _setup(db, "英语听写")
    workflow, _ = _workflow(db, ATTEMPT)
    _ask(db, workflow, session, "我写的是 beech")
    workflow.leak_judge = StaticLeakJudge(False)
    workflow.turn_model = StaticTutorModel(tutor_raw("answer", "海滩是 beach。", relation="same", depth="recall"))
    word = _ask(db, workflow, session, "海滩的英文怎么写")
    assert word.next_interaction["model_fallback"] is False and "beach" in word.next_interaction["content"]
    assert workflow.leak_judge.calls == 1
    workflow.leak_judge = StaticLeakJudge(True)
    workflow.turn_model = StaticTutorModel(tutor_raw("answer", "17×23=391。", relation="same", depth="recall"))
    product = _ask(db, workflow, session, "直接告诉我得数")
    assert product.next_interaction["model_fallback"] is True
    assert "391" not in product.next_interaction["content"]
    assert workflow.leak_judge.calls == 2


def test_cross_day_paused_session_and_stale_problem_do_not_hijack_new_turn(db):
    from datetime import datetime, timezone

    ward = create_ward(db)
    past_dt = datetime(2026, 9, 27, 7, 48, tzinfo=timezone.utc)
    task = create_task(db, ward=ward, title="英语的典范故事阅读", status="pool")
    stale_session = StudySession(
        ward_id=ward.id, task_id=task.id, status="paused",
        started_at=past_dt, last_activity_at=past_dt,
    )
    db.add(stale_session)
    db.flush()
    stale_tutor = TutoringSession(
        ward_id=ward.id, study_session_id=stale_session.id, status="active",
    )
    db.add(stale_tutor)
    db.flush()
    stale_problem = TutoringProblem(
        tutoring_session_id=stale_tutor.id, status="open",
        hints_given=1, summary="为什么不画一个图",
    )
    db.add(stale_problem)
    db.commit()

    raw = tutor_raw("answer", "太阳是恒星，地球是行星。", relation="none", topic="atomic_lookup")
    workflow, model = _workflow(db, raw)
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"content": "为我说明一下地球和太阳的区别", "tutoring_directive": "ask"},
    ))
    db.commit()

    assert '"answer_protected": false' in model.calls[0]["instruction"]
    assert outcome.next_interaction["return_to_task"] is False
    assert "先回到正在进行的任务" not in outcome.next_interaction["content"]
    db.refresh(stale_session)
    db.refresh(stale_problem)
    assert stale_session.status == "abandoned"
    assert stale_problem.status == "abandoned"


def test_new_run_without_checkpoint_abandons_leftover_open_problem_on_reused_session(db):
    ward = create_ward(db)
    session = create_study_session(db, ward=ward, task=None)
    tutor = TutoringSession(ward_id=ward.id, study_session_id=session.id, status="active")
    db.add(tutor)
    db.flush()
    leftover = TutoringProblem(
        tutoring_session_id=tutor.id, status="open", hints_given=1, summary="旧对话遗留的题目",
    )
    db.add(leftover)
    db.commit()

    raw = tutor_raw("answer", "太阳表面温度约 5500℃。", relation="none", topic="atomic_lookup")
    workflow, model = _workflow(db, raw)
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=ward.id, agent_type="tutoring",
        turn={"content": "来一些更全面详细对比", "tutoring_directive": "ask"},
        context_refs=[], resume_from_checkpoint=False,
    ))
    db.commit()

    assert '"answer_protected": false' in model.calls[0]["instruction"]
    assert outcome.next_interaction["answer_protected"] is False
    db.refresh(leftover)
    assert leftover.status == "abandoned"



def test_shown_work_turns_bind_evidence_to_the_actual_problem_and_keep_other_topics_out(db):
    from app.application.queries.tutoring_evidence import evidence_detail, list_evidence
    from app.contexts.planning.domain.scheduling import local_plan_date
    from app.infrastructure.persistence.models import TutoringMessage

    ward, session = _setup(db)
    workflow, _ = _workflow(db, ATTEMPT, ATTEMPT, KNOWLEDGE)
    _ask(db, workflow, session, "我先把已知条件写出来")
    problem = db.query(TutoringProblem).one()
    _ask(db, workflow, session, "我现在把两边相等的量列成等式")
    rows = db.query(TutoringMessage).filter_by(problem_id=problem.id).all()
    assert len(rows) == 4
    assert {row.evidence_kind for row in rows} == {"attempt", "guide"}
    day = local_plan_date(rows[-1].created_at)
    assert [item["id"] for item in list_evidence(db, ward.id, day)["items"]] == [problem.id]
    _ask(db, workflow, session, "diamond beach 是什么意思")
    detail = evidence_detail(db, ward.id, day, problem.id)
    assert len(detail["messages"]) == 4
    assert all(row["content"] != "diamond beach 是什么意思" for row in detail["messages"])


@pytest.mark.parametrize("progress", ["none", "submitted"])
def test_knowledge_scope_is_turn_local_and_return_to_old_problem_stays_protected(db, progress):
    from app.application.workflows.tutoring_workflow import _state
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy

    class ScopedJudge:
        def __init__(self):
            self.scopes = iter([True, False, True])
            self.calls = 0
        def leaks(self, **kwargs):
            self.calls += 1
            return {'leaks': False, 'reason': 'none', 'answer_protected': next(self.scopes)}

    _, session = _setup(db)
    judge = ScopedJudge()
    first = tutor_raw("guide", student_move="attempt", progress=progress, evidence="学生尝试列式")
    knowledge = tutor_raw("answer", "植物细胞有细胞壁，动物细胞没有。", relation="none")
    workflow, model = _workflow(db, first, knowledge, ATTEMPT, judge=judge)
    _ask(db, workflow, session, '练习题：四盒铅笔，每盒六支，送掉五支还剩多少？')
    old = db.query(TutoringProblem).one()
    old_counts = old.hints_given, old.substantive_attempts, old.status
    answer = _ask(db, workflow, session, '植物细胞和动物细胞有什么区别？')
    assert answer.next_interaction['answer_protected'] is False
    assert (old.hints_given, old.substantive_attempts, old.status) == old_counts
    assert TutorPermitPolicy.permit(_state(old)).answer_protected is True
    again = _ask(db, workflow, session, '回到刚才的铅笔题，先算什么？')
    assert again.next_interaction['answer_protected'] is True
    assert judge.calls == 3
    assert '"answer_protected": true' in model.calls[-1]['instruction']
