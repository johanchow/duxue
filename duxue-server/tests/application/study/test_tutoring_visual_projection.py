"""带图的答疑轮次：投影为 text_visual，计数与事实写入不受图影响，图的问题只丢图。"""

from __future__ import annotations

from app.application.ports.companion import RunInvocation
from app.application.workflows.tutor_turn import FALLBACK_TEXT, SAFE_TEXT
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.persistence.models import OutboxEvent, TutoringProblem, uid
from tests.support.factories import create_study_session, create_task, create_ward
from tests.support.fakes import (
    StaticSafetyScreening,
    StaticTutorModel,
    StaticVisualLeakJudge,
    tutor_raw,
)
from tests.unit.tutoring.test_tutor_visual import SEGMENT, STEPS


def _ask(db, workflow, session, content):
    outcome = workflow.invoke(RunInvocation(
        run_id=uid(), thread_id=uid(), ward_id=session.ward_id, agent_type="tutoring",
        turn={"study_session_id": session.id, "content": content, "tutoring_directive": "ask"},
    ))
    db.commit()
    return outcome


def _session(db):
    ward = create_ward(db)
    session = create_study_session(db, ward=ward, task=create_task(db, ward=ward, title="应用题"))
    db.commit()
    return session


def _workflow(db, raw, judge=None, safety=None):
    return TutoringWorkflow(
        db, turn_model=StaticTutorModel(raw), leak_judge=judge or StaticVisualLeakJudge(),
        safety_screening=safety,
    )


def _events(db):
    return sorted(e.payload.get("event_type") for e in db.query(OutboxEvent).all())


KNOWLEDGE_WITH_STEPS = tutor_raw("answer", "水先蒸发，再凝结，最后降下来。", relation="none", visual=STEPS)
GUIDE_WITH_SEGMENT = tutor_raw(
    "guide", "先看看小明和小红谁的份数多？", relation="same", student_move="attempt", progress="none",
    evidence="我画了线段", next_subgoal="比较两人的份数", visual=SEGMENT,
)


def test_a_kept_visual_is_projected_as_text_visual_with_inline_part(db):
    session = _session(db)
    outcome = _ask(db, _workflow(db, KNOWLEDGE_WITH_STEPS), session, "水循环是怎么回事")
    interaction = outcome.next_interaction
    assert interaction["kind"] == "text_visual" and interaction["protocol"] == "companion-interaction.v1"
    assert [part["type"] for part in interaction["parts"]] == ["text", "visual"]
    assert interaction["parts"][0]["text"] == interaction["content"]
    assert interaction["parts"][1]["visual"]["kind"] == "steps"
    assert interaction["actions"] == []  # the model can never add actions
    assert interaction["status"] == "needs_input" and interaction["act"] == "answer"


def test_without_a_visual_nothing_about_the_interaction_changes(db):
    session = _session(db)
    raw = tutor_raw("answer", "水先蒸发。", relation="none")
    interaction = _ask(db, _workflow(db, raw), session, "水循环").next_interaction
    assert "kind" not in interaction and "parts" not in interaction
    assert interaction["content"].startswith("水先蒸发。")


def test_a_diagram_does_not_change_hint_counts_or_fact_writes(db):
    with_visual, without_visual = {}, {}
    for store, raw in ((with_visual, GUIDE_WITH_SEGMENT), (without_visual, {**GUIDE_WITH_SEGMENT, "visual": None})):
        session = _session(db)
        outcome = _ask(db, _workflow(db, raw), session, "我先画了线段，小明 3 份")
        problem = db.query(TutoringProblem).one() if db.query(TutoringProblem).count() == 1 else (
            db.query(TutoringProblem).order_by(TutoringProblem.created_at.desc()).first()
        )
        store.update(
            hint_index=outcome.next_interaction["hint_index"], hints=problem.hints_given,
            attempts=problem.substantive_attempts, status=problem.status, subgoal=problem.active_subgoal,
        )
        db.query(OutboxEvent).delete()
        db.commit()
    assert with_visual == without_visual


def test_a_homework_diagram_judged_as_a_leak_is_dropped_but_the_words_stay(db):
    session = _session(db)
    judge = StaticVisualLeakJudge(result=False, visual_result=True)
    interaction = _ask(db, _workflow(db, GUIDE_WITH_SEGMENT, judge), session, "我先画了线段").next_interaction
    assert interaction["content"] == "先看看小明和小红谁的份数多？"
    assert interaction.get("kind") is None and interaction["model_fallback"] is False


def test_a_text_leak_still_replaces_the_whole_turn(db):
    session = _session(db)
    judge = StaticVisualLeakJudge(result=True, visual_result=False)
    interaction = _ask(db, _workflow(db, GUIDE_WITH_SEGMENT, judge), session, "我先画了线段").next_interaction
    assert interaction["content"] == FALLBACK_TEXT and interaction["model_fallback"] is True


def test_output_safety_review_also_reads_the_text_inside_the_diagram(db):
    seen: list[str] = []

    class Screen(StaticSafetyScreening):
        def blocks_output(self, *, text):
            seen.append(text)
            return "蒸发" in text and "降水" in text  # only true when the diagram text is included

    session = _session(db)
    raw = tutor_raw("answer", "水会变化。", relation="none", visual=STEPS)
    interaction = _ask(db, _workflow(db, raw, safety=Screen()), session, "水循环").next_interaction
    assert interaction["content"] == SAFE_TEXT and interaction["safety_blocked"] is True
    assert "降水" in seen[-1]
