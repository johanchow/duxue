from __future__ import annotations

import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai_agents.planning_domain_service import PlanningDomainService
from app.ai_agents.planning_workflow import build_planning_graph
from app.database import Base
from app.memory import MemoryAccessDenied, MemoryContextRequest, SqlAlchemyMemoryFacade
from app.models import (
    DerivedSignal,
    EpisodicMemory,
    EpisodicMemoryEvent,
    LearningEvent,
    LongTermProfile,
    Task,
    User,
    Ward,
    uid,
)


class MemoryFacadeTest(unittest.TestCase):
    def setUp(self):
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
        graph = build_planning_graph(PlanningDomainService(self.db)).compile(
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
                    }
                ],
            },
            config,
        )
        self.assertIn("__interrupt__", paused)
        completed = graph.invoke(Command(resume={"action": "confirm"}), config)
        self.assertEqual(completed["outcome"]["status"], "confirmed")
