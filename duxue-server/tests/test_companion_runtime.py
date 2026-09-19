from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.workflows.planning_domain_service import PlanningDomainService
from app.application.workflows.planning_workflow import build_planning_graph
from app.application.workflows.planning_adapter import PlanningWorkflowAdapter, planning_today
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.application.workflows.reflection_workflow import ReflectionWorkflow
from app.application.process_managers.companion_coordinator import CompanionCoordinator
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.infrastructure.ai.model_gateway import ModelGatewayError
from app.infrastructure.persistence.database import Base
from app.application.commands.memory import (
    LearningFactRecorded,
    MemoryAccessDenied,
    MemoryContextRequest,
    SqlAlchemyMemoryCommandService,
    SqlAlchemyMemoryFacade,
)
from app.application.commands.memory_worker import consume_pending_learning_facts
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.persistence.models import (
    AgentCheckpoint,
    AgentRun,
    ConversationThread,
    DerivedSignal,
    DerivedSignalEvent,
    EpisodicMemory,
    EpisodicMemoryEvent,
    LearningEvent,
    LongTermProfile,
    OutboxEvent,
    PlanDraft,
    Task,
    StudySession,
    User,
    Ward,
    uid,
)


def test_planning_today_uses_ward_local_calendar_day_at_utc_rollover():
    assert planning_today(datetime(2026, 9, 18, 16, 12, tzinfo=timezone.utc)).isoformat() == "2026-09-19"


class MemoryFacadeTest(unittest.TestCase):
    def setUp(self):
        # Unit tests must never consume a configured production model key.
        self.model_gateway = patch(
            "app.infrastructure.ai.model_gateway.QwenAgentModelGateway.generate",
            side_effect=ModelGatewayError("unit_test"),
        )
        self.model_gateway.start()
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine, expire_on_commit=False)()
        ward_user = User(type="ward")
        self.db.add(ward_user)
        self.db.flush()
        self.ward_id = ward_user.id
        self.db.add(Ward(id=self.ward_id, display_name="小读"))
        event = LearningEvent(
            ward_id=self.ward_id,
            event_type="tutoring.hint_given",
            source_type="test",
            source_id=uid(),
            source="system",
            payload={},
            scope={},
            evidence_refs=[],
        )
        self.db.add(event)
        self.db.flush()
        memory = EpisodicMemory(
            ward_id=self.ward_id,
            event_type="tutoring_episode",
            event_date=datetime.now(timezone.utc).date(),
            summary="尝试了画图后能说明关系",
            raw_cues={"skill_keys": ["math.relationship"]},
        )
        self.db.add(memory)
        self.db.flush()
        self.db.add(
            EpisodicMemoryEvent(
                episodic_memory_id=memory.id, learning_event_id=event.id
            )
        )
        self.db.add_all(
            [
                DerivedSignal(
                    ward_id=self.ward_id,
                    signal_type="effective_strategy",
                    scope="recent",
                    value={"strategy_key": "draw_diagram"},
                    statement="画图曾有帮助",
                    confidence=0.8,
                    observed_from=datetime.now(timezone.utc),
                    status="active",
                ),
                DerivedSignal(
                    ward_id=self.ward_id,
                    signal_type="knowledge_gap",
                    scope="recent",
                    value={"skill_key": "math.relationship"},
                    statement="不应泄露的候选",
                    confidence=0.3,
                    observed_from=datetime.now(timezone.utc),
                    status="candidate",
                ),
            ]
        )
        self.db.add(
            LongTermProfile(
                ward_id=self.ward_id, planning_preferences={"preference_key": "morning"}
            )
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.model_gateway.stop()

    def test_resolve_context_is_authorized_bounded_and_excludes_candidate_signals(self):
        bundle = SqlAlchemyMemoryFacade(self.db).resolve_context(
            MemoryContextRequest(
                ward_id=self.ward_id,
                actor_id=self.ward_id,
                actor_role="ward",
                use_case="tutoring",
                skill_keys=["math.relationship"],
                memory_types={"episodic", "signal", "profile"},
                visibility_scope={"ward", "system"},
                item_budget=8,
                token_budget=500,
            )
        )
        self.assertEqual(
            [item["summary"] for item in bundle.episodic_memories],
            ["尝试了画图后能说明关系"],
        )
        self.assertEqual(
            [item["statement"] for item in bundle.active_signals], ["画图曾有帮助"]
        )
        self.assertNotIn("raw_cues", bundle.episodic_memories[0])
        self.assertEqual(len(bundle.evidence_refs), 1)
        self.assertEqual(
            bundle.profile_projection["planning_preferences"],
            {"preference_key": "morning"},
        )

    def test_ward_cannot_read_another_wards_memory(self):
        with self.assertRaises(MemoryAccessDenied):
            SqlAlchemyMemoryFacade(self.db).resolve_context(
                MemoryContextRequest(
                    ward_id=self.ward_id,
                    actor_id=uid(),
                    actor_role="ward",
                    use_case="planning",
                    memory_types={"episodic"},
                    visibility_scope={"ward"},
                    item_budget=1,
                    token_budget=100,
                )
            )

    def test_plan_draft_only_writes_formal_schedule_after_confirmation(self):
        task = Task(ward_id=self.ward_id, title="数学作业")
        self.db.add(task)
        self.db.commit()
        service = PlanningDomainService(self.db)
        draft = service.save_draft(
            self.ward_id,
            datetime.now(timezone.utc).date(),
            [
                {
                    "assignment_id": task.id,
                    "new_task": False,
                    "title": task.title,
                    "planned_minutes": 30,
                    "start_at": "2026-09-16T19:00:00",
                }
            ],
        )
        self.db.commit()
        self.assertIsNone(task.schedule_id)
        schedule = service.confirm(self.ward_id, draft.id)
        self.db.commit()
        self.assertEqual(schedule.status, "confirmed")
        self.assertEqual(self.db.get(Task, task.id).schedule_id, schedule.id)

    def test_planning_graph_interrupts_then_confirms_with_same_thread(self):
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph.types import Command

        task = Task(ward_id=self.ward_id, title="英语朗读")
        self.db.add(task)
        self.db.commit()
        service = PlanningDomainService(self.db)
        save_draft = service.save_draft
        save_calls = 0

        def counted_save(*args, **kwargs):
            nonlocal save_calls
            save_calls += 1
            return save_draft(*args, **kwargs)

        service.save_draft = counted_save
        graph = build_planning_graph(service).compile(
            checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "planning-test"}}
        paused = graph.invoke(
            {
                "ward_id": self.ward_id,
                "plan_date": datetime.now(timezone.utc).date().isoformat(),
                "items": [
                    {
                        "assignment_id": task.id,
                        "new_task": False,
                        "title": task.title,
                        "planned_minutes": 20,
                        "start_at": "2026-09-16T19:00:00",
                    }
                ],
            },
            config,
        )
        self.assertIn("__interrupt__", paused)
        draft = self.db.get(PlanDraft, paused["__interrupt__"][0].value["draft_id"])
        completed = graph.invoke(Command(resume={"action": "confirm", "expected_draft_version": draft.version}), config)
        self.assertEqual(completed["outcome"]["status"], "confirmed")
        self.assertEqual(save_calls, 1)

    def test_confirm_resumes_even_if_coordinator_marked_the_run_active(self):
        """confirm_plan must not fall through to a new empty planning graph."""
        from langgraph.checkpoint.memory import InMemorySaver

        task = Task(ward_id=self.ward_id, title="数学", planned_minutes=20)
        thread = ConversationThread(ward_id=self.ward_id)
        self.db.add_all([task, thread])
        self.db.flush()
        run = AgentRun(thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
                       run_ref=f"agent_run:{uid()}", current_turn_id=uid())
        self.db.add(run)
        self.db.commit()
        adapter = PlanningWorkflowAdapter(self.db, checkpointer=InMemorySaver())
        first = adapter.invoke(invocation=RunInvocation(
            run_id=run.id, thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
            turn={"planning_items": [{"assignment_id": task.id, "new_task": False,
                                        "title": task.title, "planned_minutes": 20,
                                        "start_at": "2026-09-17T19:00:00"}]},
            turn_id=run.current_turn_id, attempt=1,
        ))
        draft = self.db.query(PlanDraft).filter_by(ward_id=self.ward_id).one()
        self.assertEqual(first.run_status, "waiting_for_ward")

        # This is exactly the state after Coordinator._start_or_resume().
        run.status, run.current_turn_id = "active", uid()
        confirmed = adapter.invoke(invocation=RunInvocation(
            run_id=run.id, thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
            turn={"structured_command": {"command": "confirm_plan", "payload": {
                "draft_id": draft.id, "expected_draft_version": draft.version,
            }}}, turn_id=run.current_turn_id, attempt=1,
        ))
        self.assertEqual(confirmed.run_status, "closed")
        self.assertEqual(confirmed.next_interaction["status"], "confirmed")

    def test_structured_clarification_reenters_review_before_issuing_confirm(self):
        """A slot form must never sign confirm_plan without a graph interrupt."""
        from langgraph.checkpoint.memory import InMemorySaver

        task = Task(ward_id=self.ward_id, title="英语听力", planned_minutes=None)
        thread = ConversationThread(ward_id=self.ward_id)
        self.db.add_all([task, thread])
        self.db.flush()
        run = AgentRun(thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
                       run_ref=f"agent_run:{uid()}", current_turn_id=uid())
        self.db.add(run)
        self.db.flush()
        draft = PlanningDomainService(self.db).save_draft(
            self.ward_id, planning_today(), [{
                "assignment_id": task.id, "new_task": False, "title": task.title,
                "planned_minutes": None, "start_at": "2026-09-18T19:30:00",
            }], pending_fields=["planned_minutes"],
        )
        slot_id = draft.working_state["active_clarification_batch"]["slots"][0]["slot_id"]
        self.db.commit()
        adapter = PlanningWorkflowAdapter(self.db, checkpointer=InMemorySaver())

        reviewed = adapter.invoke(invocation=RunInvocation(
            run_id=run.id, thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
            turn={"structured_command": {"command": "clarify_reply", "payload": {
                "answers": [{"slot_id": slot_id, "value": "30分钟"}],
            }}}, turn_id=run.current_turn_id, attempt=1,
        ))
        refreshed = self.db.get(PlanDraft, draft.id)
        self.assertEqual(reviewed.next_interaction["kind"], "plan_confirm_list")
        self.assertIsNotNone(reviewed.checkpoint_ref)

        run.status, run.current_turn_id = "active", uid()
        confirmed = adapter.invoke(invocation=RunInvocation(
            run_id=run.id, thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
            turn={"structured_command": {"command": "confirm_plan", "payload": {
                "draft_id": refreshed.id, "expected_draft_version": refreshed.version,
            }}}, turn_id=run.current_turn_id, attempt=1,
        ))
        self.assertEqual(confirmed.run_status, "closed")

    def test_clarification_outcome_can_never_issue_confirm_plan(self):
        task = Task(ward_id=self.ward_id, title="数学", planned_minutes=20)
        thread = ConversationThread(ward_id=self.ward_id)
        self.db.add_all([task, thread])
        self.db.flush()
        run = AgentRun(thread_id=thread.id, ward_id=self.ward_id, agent_type="planning",
                       run_ref=f"agent_run:{uid()}", current_turn_id=uid())
        self.db.add(run)
        draft = PlanningDomainService(self.db).save_draft(
            self.ward_id, datetime.now(timezone.utc).date(), [{
                "assignment_id": task.id, "new_task": False, "title": task.title,
                "planned_minutes": 20, "start_at": "2026-09-18T19:00:00",
            }],
        )
        outcome = PlanningWorkflowAdapter(self.db)._clarification_outcome(
            run=run, draft=draft, resolved_count=0, context_snapshot={},
        )
        assert outcome.next_interaction["kind"] == "clarify"
        assert all(action["command"] != "confirm_plan"
                   for action in outcome.next_interaction["actions"])

    def test_confirming_the_same_draft_twice_returns_the_existing_schedule(self):
        task = Task(ward_id=self.ward_id, title="科学观察")
        self.db.add(task)
        self.db.commit()
        service = PlanningDomainService(self.db)
        draft = service.save_draft(
            self.ward_id,
            datetime.now(timezone.utc).date(),
            [{"assignment_id": task.id, "new_task": False, "title": task.title, "planned_minutes": 15,
              "start_at": "2026-09-16T19:00:00"}],
        )
        first = service.confirm(self.ward_id, draft.id)
        second = service.confirm(self.ward_id, draft.id)
        self.assertEqual(first.id, second.id)
        outbox = self.db.query(OutboxEvent).one()
        self.assertEqual(outbox.event_type, "LearningFactRecorded.v1")
        self.assertEqual(outbox.payload["schema_version"], "LearningFactRecorded.v1")

    def test_memory_command_service_deduplicates_a_versioned_learning_fact(self):
        fact = LearningFactRecorded(
            ward_id=self.ward_id,
            event_type="self_review.submitted",
            source_type="self_review",
            source_id=uid(),
            occurred_at=datetime.now(timezone.utc),
            source="ward",
            visibility="ward",
        )
        service = SqlAlchemyMemoryCommandService(self.db)
        first = service.ingest_learning_fact(fact)
        second = service.ingest_learning_fact(fact)
        self.db.commit()
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(OutboxEvent).count(), 0)

    def test_closed_tutoring_facts_settle_once_with_all_evidence(self):
        service = SqlAlchemyMemoryCommandService(self.db)
        tutoring_session_id = uid()
        for event_type in (
            "tutoring.ward_attempt_recorded",
            "tutoring.hint_given",
            "tutoring.session_closed",
        ):
            service.ingest_learning_fact(LearningFactRecorded(
                ward_id=self.ward_id, event_type=event_type,
                source_type="test_tutoring", source_id=uid(),
                occurred_at=datetime.now(timezone.utc), source="system",
                payload={"tutoring_session_id": tutoring_session_id},
            ))
        first = service.settle_tutoring_episode(tutoring_session_id)
        second = service.settle_tutoring_episode(tutoring_session_id)
        self.db.commit()
        self.assertEqual(first.id, second.id)
        self.assertEqual(
            self.db.query(EpisodicMemoryEvent).filter_by(episodic_memory_id=first.id).count(), 3
        )

    def test_tutoring_workflow_records_attempt_hint_and_closed_session_for_settlement(self):
        task = Task(ward_id=self.ward_id, title="数学练习")
        self.db.add(task); self.db.flush()
        session = StudySession(ward_id=self.ward_id, task_id=task.id)
        self.db.add(session); self.db.flush()
        ledger_count = self.db.query(LearningEvent).count()
        workflow = TutoringWorkflow(self.db)
        first = workflow.invoke(RunInvocation(
            run_id=uid(), thread_id=uid(), ward_id=self.ward_id, agent_type="tutoring",
            turn={"study_session_id": session.id, "tutoring_directive": "attempt", "content": "直接告诉我答案"},
        ))
        self.assertTrue(first.next_interaction["safety_blocked"])
        closed = workflow.invoke(RunInvocation(
            run_id=uid(), thread_id=uid(), ward_id=self.ward_id, agent_type="tutoring",
            turn={"study_session_id": session.id, "tutoring_directive": "close", "content": "结束"},
        ))
        self.assertEqual(closed.run_status, "closed")
        tutor_ref = closed.context_refs[0].split(":", 1)[1]
        # The Study use case owns only its transactional Outbox.  The Memory
        # ledger is populated only once the integration events are consumed.
        self.assertEqual(self.db.query(LearningEvent).count(), ledger_count)
        service = SqlAlchemyMemoryCommandService(self.db)
        for outbox in self.db.query(OutboxEvent).order_by(OutboxEvent.created_at):
            service.ingest_learning_fact(LearningFactRecorded.model_validate(outbox.payload))
        memory = service.settle_tutoring_episode(tutor_ref)
        self.assertIsNotNone(memory)
        self.assertEqual(
            self.db.query(EpisodicMemoryEvent).filter_by(episodic_memory_id=memory.id).count(), 3
        )

    def test_closed_tutoring_session_without_interaction_does_not_settle(self):
        service = SqlAlchemyMemoryCommandService(self.db)
        tutoring_session_id = uid()
        service.ingest_learning_fact(LearningFactRecorded(
            ward_id=self.ward_id,
            event_type="tutoring.session_closed",
            source_type="test_tutoring",
            source_id=tutoring_session_id,
            occurred_at=datetime.now(timezone.utc),
            source="system",
            payload={"tutoring_session_id": tutoring_session_id},
        ))
        self.assertIsNone(service.settle_tutoring_episode(tutoring_session_id))

    def test_candidate_signal_needs_evidence_before_activation_and_challenge_removes_it(self):
        service = SqlAlchemyMemoryCommandService(self.db)
        events = []
        for _ in range(2):
            events.append(service.ingest_learning_fact(LearningFactRecorded(
                ward_id=self.ward_id, event_type="tutoring.hint_given",
                source_type="test_evidence", source_id=uid(),
                occurred_at=datetime.now(timezone.utc), source="system",
            )))
        # Long-term promotion is based on independent settled episodes, not
        # merely two messages.  Link each supporting Fact to a distinct
        # tutoring-session episode.
        for index, event in enumerate(events):
            episode = EpisodicMemory(
                ward_id=self.ward_id,
                event_type="tutoring_episode",
                memory_type="tutoring_episode",
                aggregate_ref=f"tutoring_session:{uid()}",
                aggregate_version=1,
                event_date=datetime.now(timezone.utc).date(),
                summary="独立答疑经历",
                raw_cues={},
            )
            self.db.add(episode)
            self.db.flush()
            self.db.add(EpisodicMemoryEvent(
                episodic_memory_id=episode.id, learning_event_id=event.id,
            ))
        signal = service.propose_candidate_signal(
            ward_id=self.ward_id, signal_type="effective_strategy", scope="long_term",
            dimension_key="draw_diagram", statement="画图在多个会话中有帮助",
            value={"sample_size": 2, "window": "5d", "calculation_method": "v1"},
            confidence=0.8, evidence_event_ids=[event.id for event in events],
        )
        self.assertEqual(signal.status, "candidate")
        service.evolve_signals()
        self.assertEqual(signal.status, "active")
        service.rebuild_long_term_profile(self.ward_id)
        self.assertIn("draw_diagram", self.db.get(LongTermProfile, self.ward_id).learning_strategy_profile)
        service.challenge_signal(signal.id, self.ward_id, "这不是一直有效")
        service.rebuild_long_term_profile(self.ward_id)
        self.assertEqual(signal.status, "challenged")
        self.assertNotIn("draw_diagram", self.db.get(LongTermProfile, self.ward_id).learning_strategy_profile)

    def test_evolve_signals_expires_active_signal(self):
        signal = DerivedSignal(
            ward_id=self.ward_id, signal_type="planning_preference", scope="long_term",
            dimension_key="morning", value={"sample_size": 2, "window": "5d", "calculation_method": "v1"},
            statement="过期信号", confidence=0.9, observed_from=datetime.now(timezone.utc),
            status="active", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        self.db.add(signal); self.db.flush()
        SqlAlchemyMemoryCommandService(self.db).evolve_signals()
        self.assertEqual(signal.status, "expired")

    def test_coordinator_passes_a_typed_single_run_invocation_to_dispatcher(self):
        class FakeDispatcher:
            def __init__(self):
                self.invocation = None

            def invoke(self, invocation):
                self.invocation = invocation
                return WorkflowOutcome(
                    run_status="waiting_for_ward",
                    next_interaction={"status": "needs_input"},
                    checkpoint_ref="checkpoint:planning:1",
                    context_snapshot={"version": "companion-context.v1"},
                )

        dispatcher = FakeDispatcher()
        result = CompanionCoordinator(self.db, dispatcher=dispatcher).handle(
            ward_id=self.ward_id,
            content="帮我安排明天复习",
            thread_id=None,
            expected_thread_version=0,
            route_hint=None,
        )
        self.assertEqual(dispatcher.invocation.run_id, result.run_id)
        self.assertEqual(dispatcher.invocation.agent_type, "planning")
        self.assertEqual(dispatcher.invocation.thread_id, result.thread_id)
        checkpoint = self.db.query(AgentCheckpoint).filter_by(run_id=result.run_id).one()
        self.assertEqual(checkpoint.checkpoint_ref, "checkpoint:planning:1")
        self.assertTrue(checkpoint.state_digest)

    def test_companion_command_id_replays_the_original_result_without_second_run(self):
        class FakeDispatcher:
            calls = 0

            def invoke(self, invocation):
                self.calls += 1
                return WorkflowOutcome(
                    run_status="waiting_for_ward",
                    outcome_type="waiting",
                    next_interaction={"status": "needs_input"},
                )

        dispatcher = FakeDispatcher()
        coordinator = CompanionCoordinator(self.db, dispatcher=dispatcher)
        command_id = uid()
        first = coordinator.handle(
            ward_id=self.ward_id, content="帮我安排明天复习", thread_id=None,
            expected_thread_version=0, route_hint=None, command_id=command_id,
        )
        replay = coordinator.handle(
            ward_id=self.ward_id, content="帮我安排明天复习", thread_id=None,
            expected_thread_version=0, route_hint=None, command_id=command_id,
        )
        self.assertEqual(first.model_dump(), replay.model_dump())
        self.assertEqual(dispatcher.calls, 1)

    def test_outbox_worker_ingests_and_settles_closed_tutoring_session(self):
        tutoring_session_id = uid()
        for event_type in (
            "tutoring.ward_attempt_recorded",
            "tutoring.hint_given",
            "tutoring.session_closed",
        ):
            publish_learning_fact(
                self.db,
                ward_id=self.ward_id,
                event_type=event_type,
                source_type="tutoring_message",
                source_id=uid(),
                payload={"tutoring_session_id": tutoring_session_id},
            )
        self.db.commit()
        self.assertEqual(consume_pending_learning_facts(self.db), 3)
        memory = self.db.query(EpisodicMemory).filter_by(
            memory_type="tutoring_episode",
            aggregate_ref=f"tutoring_session:{tutoring_session_id}",
        ).one()
        self.assertEqual(
            self.db.query(EpisodicMemoryEvent).filter_by(episodic_memory_id=memory.id).count(), 3
        )
        self.assertEqual(self.db.query(OutboxEvent).filter_by(status="published").count(), 3)

    def test_reflection_revisions_publish_distinct_fact_versions(self):
        workflow = ReflectionWorkflow(self.db)
        review_day = datetime.now(timezone.utc).date().isoformat()
        for feeling in ("stuck", "smooth"):
            workflow.invoke(RunInvocation(
                run_id=uid(), thread_id=uid(), ward_id=self.ward_id,
                agent_type="reflection", turn={
                    "review_date": review_day, "review_feeling": feeling,
                    "review_reflection": "补充说明", "adopt_focus_kit": False,
                },
            ))
        facts = [event.payload for event in self.db.query(OutboxEvent).filter_by(event_type="LearningFactRecorded.v1").all() if event.payload["event_type"] == "self_review.submitted"]
        self.assertEqual([fact["source_version"] for fact in facts], [1, 2])
