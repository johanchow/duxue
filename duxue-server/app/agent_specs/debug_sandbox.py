"""Production Workflow adapters backed only by a disposable, in-memory database."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def run_domain(workflow_id, data, runtime):
    from app.agent_specs.execution_trace import payload
    from app.application.ports.companion import RunInvocation
    from app.infrastructure.persistence.database import Base
    from app.infrastructure.persistence.models import (
        OutboxEvent,
        SelfReview,
        StudySession,
        Task,
        TutoringMessage,
        TutoringProblem,
        TutoringSession,
        User,
        Ward,
        uid,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            ward_id = uid()
            db.add(User(id=ward_id, type="ward"))
            db.add(Ward(id=ward_id, display_name="调试孩子"))
            db.flush()
            task = None
            if data.context.task_title:
                task = Task(
                    ward_id=ward_id, title=data.context.task_title, status="pool"
                )
                db.add(task)
                db.flush()
            session = StudySession(
                ward_id=ward_id, task_id=task.id if task else None, status="active"
            )
            db.add(session)
            db.flush()
            if data.problem:
                tutor = TutoringSession(
                    ward_id=ward_id,
                    study_session_id=session.id,
                    question_summary=data.problem,
                )
                db.add(tutor)
                db.flush()
                db.add(
                    TutoringProblem(
                        tutoring_session_id=tutor.id,
                        summary=data.problem,
                        **data.context.model_dump(
                            include={
                                "active_subgoal",
                                "substantive_attempts",
                                "hints_given",
                                "evidence_summary",
                            }
                        ),
                        status=data.context.problem_status,
                    )
                )
                db.flush()
            window = [row.model_dump() for row in data.context.history]
            if data.problem and not window:
                window = [{"author": "ward", "text": data.problem}]
            if workflow_id == "tutoring":
                from app.application.workflows.tutoring_workflow import TutoringWorkflow
                from app.infrastructure.ai.tutor_turn_model import (
                    QwenLeakJudge,
                    QwenTutorTurnGateway,
                )

                class SandboxTutoring(TutoringWorkflow):
                    def _media(self, invocation):
                        return window, []

                workflow = SandboxTutoring(
                    db,
                    turn_model=QwenTutorTurnGateway(settings_obj=runtime),
                    backup_model=QwenTutorTurnGateway(
                        settings_obj=runtime, component_id="tutoring.turn-backup"
                    ),
                    leak_judge=QwenLeakJudge(settings_obj=runtime),
                )
            else:
                from app.application.workflows.reflection_workflow import (
                    ReflectionWorkflow,
                )

                workflow = ReflectionWorkflow(db)
            invocation = RunInvocation(
                run_id=uid(),
                thread_id=uid(),
                ward_id=ward_id,
                agent_type=workflow_id,
                turn={
                    "content": data.content,
                    "study_session_id": session.id,
                    **(
                        {
                            "review_date": data.context.review_date.isoformat(),
                            "review_feeling": data.context.review_feeling,
                            "review_reflection": data.context.review_reflection
                            or data.content,
                        }
                        if data.context.review_date
                        else {}
                    ),
                },
            )
            outcome = workflow.invoke(invocation)
            db.flush()
            interaction = outcome.next_interaction or {}
            result = {
                "content": interaction.get("content", interaction.get("text", "")),
                "output": outcome.model_dump(mode="json"),
                "status": "succeeded",
                "sandbox_effects": {
                    "learning_facts": [
                        payload(row.payload) for row in db.query(OutboxEvent).all()
                    ],
                    "self_reviews": [
                        {
                            "review_date": str(row.review_date),
                            "feeling": row.feeling,
                            "reflection": row.reflection,
                        }
                        for row in db.query(SelfReview).all()
                    ],
                    "messages": [
                        {"role": row.role, "content": row.content}
                        for row in db.query(TutoringMessage).all()
                    ],
                    "problems": [
                        {
                            "status": row.status,
                            "summary": row.summary,
                            "hints_given": row.hints_given,
                        }
                        for row in db.query(TutoringProblem).all()
                    ],
                },
            }
            if interaction.get("safety_blocked"):
                result["status"] = "blocked"
            # The Workflow exposes fallback status; a safe fallback is not a successful model result.
            if interaction.get("model_fallback"):
                result["status"] = "failed"
            db.rollback()
            return result
    finally:
        engine.dispose()


def run_simple(workflow_id, data):
    if workflow_id == "review-aspects":
        from app.application.queries.review_draft import propose_review_aspects

        return propose_review_aspects(data.content)
    if workflow_id == "sprint-intake":
        from app.application.queries.sprint_preview import (
            SprintPreviewRequest,
            preview_spoken_sprint,
        )

        return preview_spoken_sprint(SprintPreviewRequest(content=data.content))
    from app.api.schemas import TaskIntakeRequest
    from app.application.commands.task_intake import TaskIntakeService

    # Authorization fixtures are synthetic and confined to this call.
    return (
        TaskIntakeService()
        .respond(
            wards=[{"id": "debug-ward", "display_name": "调试孩子"}],
            request=TaskIntakeRequest(content=data.content),
        )
        .model_dump(mode="json")
    )
