from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.agent_specs.execution_trace import transition
from app.application.commands.memory import SqlAlchemyMemoryFacade
from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.application.ports.tutoring import SafetyScreeningPort
from app.application.queries.context_builder import ContextBuilder
from app.application.queries.self_reviews import get_recent_self_reviews
from app.application.workflows.planning_adapter import planning_today
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.application.workflows.pronunciation_guidance import (
    build_interaction,
    project_lesson,
)
from app.application.workflows.teaching_skills import history_candidates
from app.application.workflows.tutor_loop import (
    JUDGE_RECENT_PROBLEMS,
    TurnResult,
    judge_problem_summary,
    run_tutor_turn,
)
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutor_turn import (
    REMINDER,
    SAFE_TEXT,
    LeakJudgePort,
    TutorModelPort,
    build_tutor_instruction,
    fallback_text,
)
from app.application.workflows.tutor_visual import SearchPhoto, describe
from app.contexts.companion.domain.policy import PolicyRegistry
from app.contexts.tutoring.domain.tutor_permit import (
    PROTECTED_STATUSES,
    ProblemAssessment,
    ProblemState,
    TutorPermitPolicy,
)
from app.infrastructure.ai import components
from app.infrastructure.ai.prompts import render_fragment
from app.infrastructure.messaging.outbox import publish_learning_fact
from app.infrastructure.observability.telemetry import (
    agent_infra_span,
    agent_step_span,
    record_llm_fallback,
    record_tutor_turn_result,
    set_observation_payload,
    stage_tutor_subgoal_transition,
    traced_agent_node,
)
from app.infrastructure.persistence.models import (
    StudySession,
    StudySessionInterval,
    Task,
    TutoringMessage,
    TutoringProblem,
    TutoringSession,
    Ward,
    now,
)


def _state(row: TutoringProblem | None) -> ProblemState | None:
    if row is None:
        return None
    return ProblemState(
        status=row.status, active_subgoal=row.active_subgoal,
        substantive_attempts=row.substantive_attempts, hints_given=row.hints_given,
        evidence_summary=row.evidence_summary,
    )


def _store(row: TutoringProblem, state: ProblemState) -> None:
    row.status = state.status
    row.active_subgoal = state.active_subgoal
    row.substantive_attempts = state.substantive_attempts
    row.hints_given = state.hints_given
    row.evidence_summary = state.evidence_summary


class TutoringWorkflow:
    """tutor-turn.v4：模型驱动一轮，代码守住入口许可和出口检查。"""

    def __init__(
        self, db: Session, turn_model: TutorModelPort | None = None, leak_judge: LeakJudgePort | None = None,
        safety_screening: SafetyScreeningPort | None = None,
        backup_model: TutorModelPort | None = None,
        image_target_selector: Callable[[list[dict], str], dict] | None = None,
        math_engine=None,
        blueprint_planner=None,
        dossier_enqueue_fn: Callable[..., None] | None = None,
        first_turn_solve_budget_seconds: float | None = None,
    ):
        import os

        self.math_engine = math_engine
        self.blueprint_planner = blueprint_planner
        self.dossier_enqueue_fn = dossier_enqueue_fn
        self.first_turn_solve_budget_seconds = (
            first_turn_solve_budget_seconds
            if first_turn_solve_budget_seconds is not None
            else float(os.getenv("SOLVE_FIRST_TURN_BUDGET_SECONDS", "0"))
        )
        self.db = db
        self.turn_model = turn_model
        self.backup_model = backup_model
        self._live_turn_model = turn_model is None
        self.leak_judge = leak_judge
        self.safety_screening = safety_screening
        self.image_target_selector = image_target_selector
        self._media_cache: dict[str, tuple[list[dict], list[str | None], dict[str, str]]] = {}
        self._selected_image_refs: dict[str, list[str]] = {}

    def _dossier_mode_enabled(self) -> bool:
        if self.dossier_enqueue_fn is not None:
            return True
        if self._live_turn_model:
            from app.agent_specs.definitions import load_definitions
            from app.agent_specs.gaokao_contracts import PLANNER_ID

            return PLANNER_ID in load_definitions().units
        return False

    def _resolve_active_dossier(
        self,
        *,
        ward_id: str,
        problem_row: TutoringProblem | None,
        content: str,
        images: list[str],
        attachment_keys: list[str],
        tutoring_intent: str | None,
    ):
        """Read-only lookup of an existing `ProblemDossier` (open problem or ward/bank cache).

        New dossiers are NEVER created or enqueued before the turn is classified and vetted;
        deferred creation happens exclusively in `apply_work()` for verified reasoning work.
        """
        _ = attachment_keys
        from app.agent_specs.image_refs import image_ref
        from app.application.ports.problem_solving import SqlProblemDossierRepository
        from app.application.queries.problem_dossier import GetProblemDossierQuery
        from app.contexts.problem_solving.domain.dossier import StructuredStem, image_request_fingerprint

        query = GetProblemDossierQuery(self.db)
        if problem_row is not None and problem_row.dossier_id:
            dossier, projection = query.tutoring_view(
                ward_id=ward_id,
                dossier_id=problem_row.dossier_id,
                student_progress=problem_row.milestone_progress or {},
            )

            if images and dossier is not None:
                if dossier.evidence.get("request_image_refs") != [image_ref(img) for img in images]:
                    # The model will decide whether this is new work or another photo of the same work.
                    return None, None
            return dossier, projection

        if (
            tutoring_intent == "pronunciation"
            or (not content.strip() and not images)
            or problem_row is not None
            or not self._dossier_mode_enabled()
        ):
            return None, None

        repo = SqlProblemDossierRepository(self.db)
        stem = StructuredStem.from_request(content)
        if images:
            fp = image_request_fingerprint(stem, [image_ref(img) for img in images])
            cached = repo.find_image_request(ward_id=ward_id, fingerprint=fp)
        else:
            cached = repo.find_reusable(stem=stem, ward_id=ward_id)
        if cached is not None and cached.status in {"ready", "low_confidence"}:
            return cached, cached.tutoring_projection(student_progress={})
        return None, None

    def _planner(self):
        if self.blueprint_planner is not None:
            return self.blueprint_planner
        if self._live_turn_model:
            from app.application.workflows.blueprint_planner import (
                QwenBlueprintPlannerGateway,
            )

            self.blueprint_planner = QwenBlueprintPlannerGateway()
            return self.blueprint_planner
        return None

    def _model(self) -> TutorModelPort:
        if self.turn_model is None:
            from app.infrastructure.ai.tutor_turn_model import QwenTutorTurnGateway
            self.turn_model = QwenTutorTurnGateway()
        return self.turn_model

    def _backup_model(self) -> TutorModelPort | None:
        if self.backup_model is None and self._live_turn_model:
            from app.infrastructure.ai.tutor_turn_model import QwenTutorTurnGateway
            self.backup_model = QwenTutorTurnGateway(component_id="tutoring.turn-backup")
        return self.backup_model

    def _judge(self) -> LeakJudgePort:
        if self.leak_judge is None:
            from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge
            self.leak_judge = QwenLeakJudge()
        return self.leak_judge

    def _safety(self) -> SafetyScreeningPort:
        if self.safety_screening is None:
            from app.infrastructure.ai.tutoring_safety import LocalSafetyScreening
            self.safety_screening = LocalSafetyScreening()
        return self.safety_screening

    def _media(self, invocation: RunInvocation) -> tuple[list[dict], list[str | None], dict[str, str]]:
        """Window rows with their images, plus this turn's images. Read once per turn."""
        key = f"{invocation.run_id}:{invocation.turn_id}"
        if key not in self._media_cache:
            from app.agent_specs.image_refs import image_ref
            from app.application.queries.run_transcript import (
                _default_reader,
                current_turn_images,
                load_visible_utterances,
            )

            keys_by_ref = {}

            def read_image(attachment_key):
                url = _default_reader(attachment_key)
                keys_by_ref[image_ref(url)] = attachment_key
                return url

            with agent_infra_span("tutoring.load_media") as media_span:
                current = current_turn_images(invocation.ward_id, invocation.turn.get("attachment_keys"), read_image=read_image)
                image_budget = 8
                if current:
                    image_budget = 1 if any(current) and invocation.turn.get("tutoring_intent") == "compare_previous_image" else 0
                elif (
                    invocation.turn.get("history_image_ref") == "none"
                    and invocation.turn.get("tutoring_intent") != "compare_previous_image"
                ):
                    image_budget = 0
                window = load_visible_utterances(
                    self.db, ward_id=invocation.ward_id, thread_id=invocation.thread_id,
                    exclude_turn_id=invocation.turn_id, image_budget=image_budget, read_image=read_image,
                )
                media_span.set_attribute("media.window_count", len(window))
                media_span.set_attribute("media.image_budget", image_budget)
                media_span.set_attribute("media.current_images", len(current))
                media_span.set_attribute(
                    "media.window_images",
                    sum(len(row.get("image_urls") or []) for row in window),
                )
            self._media_cache[key] = (window, current, keys_by_ref)
        return self._media_cache[key]

    def invoke(self, invocation: RunInvocation) -> WorkflowOutcome:
        from app.agent_specs.release_runtime import pin_release
        with pin_release():
            key = f"{invocation.run_id}:{invocation.turn_id}"
            try:
                outcome = self._turn(invocation)
                refs = self._selected_image_refs.get(key, [])
                if refs and outcome.next_interaction is not None:
                    outcome.next_interaction["image_target_refs"] = list(refs)
                return outcome
            finally:
                self._selected_image_refs.pop(key, None)
                self._media_cache.pop(key, None)

    def _find_session(self, ward_id: str, session_id: str | None) -> StudySession | None:
        if session_id:
            session = self.db.get(StudySession, session_id)
            if session is None:
                raise HTTPException(404, "study session not found")
            if session.ward_id != ward_id:
                raise HTTPException(403, "study session does not belong to Ward")
            return session
        PlanningDomainService(self.db).release_unfinished_tasks(ward_id, planning_today())
        return (
            self.db.query(StudySession)
            .filter(StudySession.ward_id == ward_id, StudySession.status.in_(("active", "paused")))
            .order_by(StudySession.started_at.desc())
            .first()
        )

    def _create_session(self, ward_id: str) -> StudySession:
        session = StudySession(ward_id=ward_id, task_id=None, status="active")
        self.db.add(session)
        self.db.flush()
        self.db.add(StudySessionInterval(study_session_id=session.id))
        publish_learning_fact(
            self.db, ward_id=ward_id, event_type="study_session.started",
            source_type="study_session", source_id=session.id, payload={"task_id": None},
        )
        return session

    def _ensure_tutor(self, ward_id, session, tutor, content):
        """写入前才打开会话。发音和澄清是只读的，不会走到这里。"""
        session = session or self._create_session(ward_id)
        if tutor is None:
            tutor = TutoringSession(
                ward_id=session.ward_id, study_session_id=session.id,
                question_summary=content, model_name=components.model_for("tutoring.turn"),
            )
            self.db.add(tutor)
            self.db.flush()
        return session, tutor

    def _open_problem(self, tutor: TutoringSession) -> TutoringProblem | None:
        """The latest problem whose answer is still protected: `open`, or `submitted`.

        A submission is the Ward's proposal, not permission to show the answer, so it stays
        in force until a code policy releases it (see ``tutor_permit.Disclosure``)."""
        return (
            self.db.query(TutoringProblem)
            .filter(
                TutoringProblem.tutoring_session_id == tutor.id,
                TutoringProblem.status.in_(sorted(PROTECTED_STATUSES)),
            )
            .order_by(TutoringProblem.created_at.desc())
            .first()
        )

    def _recent_problem_summaries(self, tutor: TutoringSession | None) -> list[str]:
        """Newest first, whatever the status: the leak judge must still recognise a problem
        the model labelled as abandoned with `relation=new`."""
        if tutor is None:
            return []
        rows = (
            self.db.query(TutoringProblem.summary)
            .filter(TutoringProblem.tutoring_session_id == tutor.id)
            .order_by(TutoringProblem.created_at.desc())
            .limit(JUDGE_RECENT_PROBLEMS)
            .all()
        )
        return [row.summary for row in rows if row.summary]

    def _task_title(self, task_id: str | None) -> str | None:
        task = self.db.get(Task, task_id) if task_id else None
        return task.title if task is not None else None

    @traced_agent_node("tutoring.model_loop")
    def _run_model(self, envelope, instruction, window, images, tools: TutorToolbox, **checks) -> TurnResult | None:
        """有界循环、出口检查与泄露后的一次重试由 tutor_loop 提供（评测共用）。"""
        try:
            model = self._model()
        except Exception as error:  # noqa: BLE001 - model setup failures use the safe fallback
            record_llm_fallback(operation="tutor_turn", reason=str(error))
            return None
        return run_tutor_turn(
            model, envelope, instruction, window, images, tools, leak_judge=self._judge(),
            backup_model=self._backup_model(), **checks,
        )

    @staticmethod
    def _judge_images(window: list[dict], current_images: list[str | None]) -> list[str]:
        """Only already-authorized conversation images may reach the leak judge.

        This is deliberately assembled after ``_media()``: it adds no image reading,
        extraction, persistence, or cross-thread lookup. ``run_tutor_turn`` sends it
        only after its normal protected-work decision requires a text leak check.
        """
        return [
            image for image in [
                *(url for row in window for url in (row.get("image_urls") or [])),
                *current_images,
            ] if isinstance(image, str) and image
        ]

    @staticmethod
    def _select_image_target(window: list[dict], content: str) -> dict:
        from app.agent_specs.catalog import load_catalog
        from app.agent_specs.contexts import build_context
        from app.infrastructure.ai.components import invoke_agent_component

        user = build_context("tutoring.image-target", content=content, window=window)
        return invoke_agent_component(spec=load_catalog().component("tutoring", "image_target"), user=user).unwrap()

    @traced_agent_node("tutoring.turn")
    def _turn(self, invocation: RunInvocation) -> WorkflowOutcome:
        from app.agent_specs.catalog import load_catalog
        from app.application.workflows.tutoring_turn_execution import execute_turn

        turn = _TutoringTurn(self, invocation)
        spec = load_catalog().spec("tutoring")
        if spec.execution == "turn_graph" and invocation.turn.get("tutoring_graph_version", "turn_graph") == "turn_graph":
            return execute_turn(spec, turn)
        return self._legacy_turn(turn)

    @staticmethod
    def _legacy_turn(turn) -> WorkflowOutcome:
        """Compatibility for pinned releases published before executable tutoring graphs."""
        transition("tutoring", "START", "tutoring.turn")
        if turn.load() == "closing":
            return turn.close()
        intake = turn.intake()
        if intake == "unsafe_input":
            return turn.blocked_input()
        if intake == "confirmed":
            return turn.understood()
        if turn.media_access() == "foreign_media":
            return turn.reject_media()
        image_result = turn.select_images()
        has_images = bool(turn.images or any(row.get("image_urls") for row in turn.window))
        if has_images:
            transition("tutoring", "tutoring.turn", "tutoring.image_target", "image_reference")
        if image_result == "ambiguous":
            return turn.clarify_image()
        transition("tutoring", "tutoring.image_target" if has_images else "tutoring.turn",
                   "tutoring.model_loop", "resolved" if has_images else "ready")
        turn.read_self_review()
        turn.generate()
        if turn.vetting:
            transition("tutoring", "tutoring.exit_gate", "tutoring.output_safety", "checked")
        decision = turn.screen()
        if decision == "work":
            transition("tutoring", "tutoring.output_safety", "tutoring.apply_problem", "accepted_work")
            turn.apply_work()
            transition("tutoring", "tutoring.apply_problem", "tutoring.result")
        else:
            transition("tutoring", "tutoring.output_safety", "tutoring.result", "fallback_or_readonly")
        return {
            "pronounce": turn.pronounce, "clarify": turn.clarify,
            "failed": turn.fallback, "unsafe_output": turn.blocked_output,
            "work": turn.answer, "conversation": turn.answer,
        }[decision]()

    @traced_agent_node("tutoring.apply_problem")
    def _apply_problem(
        self, tutor, row, candidate, verdict, invocation, *, has_work_input, summary,
        planned_blueprint=None, planned_group=None, dossier_id: str | None = None,
    ):
        """按 `TutorPermitPolicy.advance()` 推进题目记录。返回（题目状态，本轮提示序号，是否计了一次实质尝试）。

        同一个 Ward Turn 的重放不重复计数：记录已处理过本 turn 时原样返回。
        """
        from app.contexts.tutoring.domain.blueprint import (
            BlueprintProgressPolicy,
            SolutionBlueprint,
        )

        new_problem = candidate.relation in {"new", "subproblem"}
        if row is not None and not new_problem and row.last_turn_id == invocation.turn_id:
            return row.status, None, False, row.id
        if row is None or new_problem:
            if row is not None:
                row.status = "abandoned"
            initial_progress = {}
            if candidate.work and candidate.work.completed_milestone_id:
                initial_progress[candidate.work.completed_milestone_id] = "completed"
            row = TutoringProblem(
                tutoring_session_id=tutor.id,
                dossier_id=dossier_id,
                summary=summary[:500],
                internal_blueprint=planned_blueprint.to_dict() if planned_blueprint is not None else None,
                milestone_progress=initial_progress or None,
                group_context=planned_group.to_dict() if planned_group is not None else None,
            )
            self.db.add(row)
            self.db.flush()
        else:
            if dossier_id and not row.dossier_id:
                row.dossier_id = dossier_id
            if row.dossier_id and candidate.work and candidate.work.completed_milestone_id:
                prog = dict(row.milestone_progress or {})
                prog[candidate.work.completed_milestone_id] = "completed"
                row.milestone_progress = prog
            elif row.internal_blueprint and candidate.work:
                bp_vo = SolutionBlueprint.from_dict(row.internal_blueprint)
                updated_bp = BlueprintProgressPolicy.advance(
                    bp_vo,
                    completed_milestone_id=candidate.work.completed_milestone_id,
                    adopted_approach_id=candidate.work.adopted_approach_id,
                )
                if updated_bp is not None:
                    row.internal_blueprint = updated_bp.to_dict()
        assessment = ProblemAssessment(
            effective_work_product=True, student_move=candidate.student_move,
            progress=candidate.progress, act=candidate.act,
            counts_as_attempt=has_work_input, subgoal_evidence=candidate.subgoal_evidence,
            next_subgoal=candidate.next_subgoal,
        )
        before = _state(row)
        new = TutorPermitPolicy.advance(before, assessment)
        _store(row, new)
        stage_tutor_subgoal_transition(
            problem_id=row.id, turn_id=invocation.turn_id,
            previous=before.active_subgoal, candidate=candidate.next_subgoal,
            applied=new.active_subgoal,
        )
        row.last_turn_id = invocation.turn_id
        hint_index = new.hints_given if new.hints_given > before.hints_given else None
        return row.status, hint_index, new.substantive_attempts > before.substantive_attempts, row.id

    def _reply(self, invocation, tutor, refs, envelope, *, text, blocked, permit, problem_status):
        self.db.add(TutoringMessage(tutoring_session_id=tutor.id, role="assistant", content=text, safety_blocked=blocked))
        self.db.flush()
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=refs,
            next_interaction={
                "status": "needs_input", "content": text, "problem_status": problem_status,
                "answer_protected": permit.answer_protected,
                "safety_blocked": blocked, "return_to_task": False,
                "model": components.model_for("tutoring.turn"), "model_fallback": not blocked,
            },
            context_snapshot=envelope.trace_snapshot(),
        )

    def _ward_message(self, tutor, content):
        message = TutoringMessage(tutoring_session_id=tutor.id, role="ward", content=content)
        self.db.add(message)
        self.db.flush()
        return message


class _TutoringTurn:
    """Request-local business operations shared by the legacy and graph entry points."""

    def __init__(self, owner: TutoringWorkflow, invocation: RunInvocation):
        self.owner = owner
        self.invocation = invocation
        self.review_aspects = []
        self.ward_msg = None
        self.hint_index = None
        self.attempted = False
        self.evidence_problem_id = None

    def load(self):
        self.turn = self.invocation.turn
        policy = PolicyRegistry()
        ward = self.owner.db.get(Ward, self.invocation.ward_id)
        self.grade_stage = ward.grade_stage if isinstance(ward, Ward) else None
        self.envelope = ContextBuilder(SqlAlchemyMemoryFacade(self.owner.db)).build(
            run_id=self.invocation.run_id, ward_id=self.invocation.ward_id, actor_id=self.invocation.ward_id,
            actor_role="ward", agent_type="tutoring", context_refs=self.invocation.context_refs,
            context_spec=policy.context_spec("tutoring"),
            grade_stage=self.grade_stage,
        )
        self.session = self.owner._find_session(self.invocation.ward_id, self.turn.get("study_session_id"))
        self.tutor = (
            self.owner.db.query(TutoringSession).filter_by(study_session_id=self.session.id).one_or_none()
            if self.session is not None else None
        )
        self.directive = self.turn.get("tutoring_directive") or "ask"
        return "closing" if self.directive == "close" else "open"

    def close(self):
        if self.tutor is None:
            raise HTTPException(409, "there is no tutoring session to close")
        if self.tutor.status != "closed":
            self.tutor.status = "closed"
            self.tutor.closed_at = now()
        publish_learning_fact(
            self.owner.db, ward_id=self.session.ward_id, event_type="tutoring.session_closed",
            source_type="tutoring_session", source_id=self.tutor.id,
            payload={"tutoring_session_id": self.tutor.id, "study_session_id": self.session.id},
        )
        return WorkflowOutcome(
            run_status="closed", outcome_type="completed", context_refs=[f"tutoring_session:{self.tutor.id}"],
            next_interaction={"status": "closed"}, context_snapshot=self.envelope.trace_snapshot(),
        )

    def intake(self):
        if self.tutor is not None and self.tutor.status == "closed":
            raise HTTPException(409, "tutoring session is closed")
        if self.session is not None and self.session.status not in {"active", "paused"}:
            raise HTTPException(409, "study session is no longer open for tutoring")

        self.content = self.turn.get("content", "")
        if (
            self.tutor is not None
            and not self.invocation.resume_from_checkpoint
            and not self.invocation.context_refs
            and not self.turn.get("study_session_id")
        ):
            for stale_problem in (
                self.owner.db.query(TutoringProblem)
                .filter(
                    TutoringProblem.tutoring_session_id == self.tutor.id,
                    TutoringProblem.status.in_(sorted(PROTECTED_STATUSES)),
                )
                .all()
            ):
                stale_problem.status = "abandoned"
        self.problem_row = self.owner._open_problem(self.tutor) if self.tutor is not None else None
        self.problem_status = self.problem_row.status if self.problem_row else None
        self.permit = TutorPermitPolicy.permit(_state(self.problem_row))
        self.task_title = self.owner._task_title(self.session.task_id if self.session else None)
        self.task_active = bool(self.session and self.session.task_id and self.session.status in {"active", "paused"})
        if self.owner._safety().blocks_input(text=self.content):
            return "unsafe_input"
        return "confirmed" if self.directive == "understood" else "question"

    def blocked_input(self):
        self.session, self.tutor = self.owner._ensure_tutor(self.invocation.ward_id, self.session, self.tutor, self.content)
        self.refs = [f"tutoring_session:{self.tutor.id}"]
        self.owner._ward_message(self.tutor, self.content)
        return self.owner._reply(
            self.invocation, self.tutor, self.refs, self.envelope, text=SAFE_TEXT, blocked=True,
            permit=self.permit, problem_status=self.problem_row.status if self.problem_row else None,
        )

    def understood(self):
        self.session, self.tutor = self.owner._ensure_tutor(self.invocation.ward_id, self.session, self.tutor, self.content)
        self.ward_msg = self.owner._ward_message(self.tutor, self.content)
        publish_learning_fact(
            self.owner.db, ward_id=self.session.ward_id, event_type="tutoring.understanding_confirmed",
            source_type="tutoring_message", source_id=self.ward_msg.id, source="ward", visibility="ward",
            payload={"tutoring_session_id": self.tutor.id, "study_session_id": self.session.id},
        )
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=[f"tutoring_session:{self.tutor.id}"],
            next_interaction={"status": "understood", "problem_status": self.problem_row.status if self.problem_row else None,
                              "answer_protected": self.permit.answer_protected, "safety_blocked": False},
            context_snapshot=self.envelope.trace_snapshot(),
        )

    def media_access(self):
        from app.application.queries.run_transcript import ward_media_prefix

        prefix = ward_media_prefix(self.invocation.ward_id)
        return "foreign_media" if any(not str(key).startswith(prefix) for key in self.turn.get("attachment_keys") or []) else "authorized"

    def reject_media(self):
        interaction = build_interaction(
            invocation=self.invocation, kind="text", text="这次不能读取这张图片。请重新拍一张再发。",
        )
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="response",
            next_interaction={**interaction, "status": "rejected", "reason": "unauthorized_media"},
        )

    def select_images(self):
        self.window, self.images, self.keys_by_ref = self.owner._media(self.invocation)
        from app.application.workflows.image_target import (
            prepare_images,
        )

        self.prepared = prepare_images(
            self.window, self.images, content=self.content,
            compare_previous=self.turn.get("tutoring_intent") == "compare_previous_image",
            select=self.owner.image_target_selector or self.owner._select_image_target,
        )
        target = self.prepared.target
        with agent_step_span("check", "tutoring.image_target") as target_span:
            set_observation_payload(target_span, input={
                "candidate_count": sum(len(row.get("image_urls") or []) for row in self.window) + len(self.images),
                "current_image_count": len(self.images),
            }, output={"target_image_ids": list(target.ids), "ambiguous": target.ambiguous})
        return "ambiguous" if target.ambiguous else "resolved"

    def clarify_image(self):
        interaction = build_interaction(
            invocation=self.invocation, kind="text",
            text=("你想让我检查哪张已上传的照片？请说第几张，我会继续用原图检查。"
                  if any(self.images) or any(url for row in self.window for url in row.get("image_urls", []))
                  else "这次图片没有读取成功，请重新上传或拍清楚一些，我再帮你检查。"),
        )
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="response",
            next_interaction={**interaction, "status": "clarification_required", "reason": "image_target_ambiguous"},
        )

    def read_self_review(self):
        self.review_aspects = get_recent_self_reviews(
            self.owner.db, actor_id=self.invocation.ward_id, actor_role="ward",
            ward_id=self.invocation.ward_id, use_case="tutoring", end_date=planning_today(),
            task_ref=self.session.task_id, item_budget=4,
        ) if self.session and self.session.task_id else []
        return "context_ready"

    def generate(self):
        self.window, self.images = self.prepared.window, self.prepared.images
        self.owner._selected_image_refs[f"{self.invocation.run_id}:{self.invocation.turn_id}"] = self.prepared.refs
        candidates = history_candidates(self.window)
        instruction = build_tutor_instruction(
            content=self.content, permit=self.permit, history_candidates=candidates,
            tutoring_intent=self.turn.get("tutoring_intent"),
            self_review_aspects=self.review_aspects,
        )
        if any(row.get("shown_visual_kind") for row in self.window):
            instruction += "\n参考历史中实际展示的 shown_visual_kind。学生要求换成更直观的图时，选择能表现原理的图形，避免重复已有表格。"
        if self.prepared.target.ids:
            instruction += render_fragment("tutoring.turn", "image_review")
            if self.turn.get("tutoring_intent") == "compare_previous_image":
                instruction += render_fragment("tutoring.turn", "image_compare")
        tools = TutorToolbox(
            self.owner.db, tutoring_session_id=self.tutor.id if self.tutor else None, problem=self.problem_row,
            task_title=self.task_title, task_active=self.task_active, window=self.window, math_engine=self.owner.math_engine,
        )
        self.all_authorized_images = self.owner._judge_images(self.window, self.images)
        self.selected_attachment_keys = [self.keys_by_ref[ref] for ref in self.prepared.refs if ref in self.keys_by_ref]
        self.active_dossier, dossier_projection = self.owner._resolve_active_dossier(
            ward_id=self.invocation.ward_id,
            problem_row=self.problem_row,
            content=self.content,
            images=self.all_authorized_images,
            attachment_keys=self.selected_attachment_keys,
            tutoring_intent=self.turn.get("tutoring_intent"),
        )
        model_envelope = self.envelope.model_dump()
        if self.active_dossier is not None:
            model_envelope["_dossier_gate"] = {
                "dossier_id": self.active_dossier.dossier_id,
                "status": self.active_dossier.status,
                "confidence": self.active_dossier.confidence,
                "allows_verdict_assertion": self.active_dossier.allows_verdict_assertion(),
            }
            if self.active_dossier.status in {"ready", "low_confidence"} and dossier_projection is not None:
                model_envelope["problem_dossier"] = dossier_projection
            if self.active_dossier.status == "ready":
                # P2: Follow-up turns backed by a ready dossier (T1 medium or T2/bank high)
                # already receive structured approaches/milestones, so run on the lightweight
                # non-thinking tier while `_dossier_gate` still enforces strict `high`-only verdict rules.
                model_envelope["_disable_thinking"] = True
        elif self.owner._dossier_mode_enabled():
            # Always enforce confidence gate on unbacked first turns (e.g. deferred text dossier creation)
            # so mental-math final/optimality affirmations are never silently allowed.
            model_envelope["_dossier_gate"] = {
                "dossier_id": None,
                "status": "absent",
                "confidence": "low",
                "allows_verdict_assertion": False,
            }
        if (
            self.turn.get("disable_thinking") is True
            and self.active_dossier is None
        ):
            model_envelope["_disable_thinking"] = True
        elif (
            not model_envelope.get("_disable_thinking")
            and self.active_dossier is None
            and isinstance(model_envelope.get("actor"), dict)
            and model_envelope["actor"].get("grade_stage") == "primary"
        ):
            model_envelope["_thinking_budget"] = 1024
        if self.problem_row is not None and (not self.problem_row.dossier_id or self.active_dossier is not None):
            if self.problem_row.internal_blueprint and "problem_dossier" not in model_envelope:
                model_envelope["internal_blueprint"] = self.problem_row.internal_blueprint
            if self.problem_row.group_context:
                model_envelope["group_context"] = self.problem_row.group_context
        high_conf_finals = (
            self.active_dossier.final_answers
            if self.active_dossier is not None
            and self.active_dossier.status == "ready"
            and self.active_dossier.confidence == "high"
            and self.active_dossier.final_answers
            else None
        )
        judge_utterances = (
            []
            if self.images and self.turn.get("history_image_ref") == "none"
            else self.window
        )
        result = self.owner._run_model(
            model_envelope, instruction, self.window, self.images, tools, permit=self.permit, task_title=self.task_title,
            problem_summary=judge_problem_summary(
                self.owner._recent_problem_summaries(self.tutor), self.content, recent_utterances=judge_utterances,
                verified_final_answers=high_conf_finals,
            ),
            judge_images=self.all_authorized_images,
        )
        self.candidate = self.verdict = self.visual = None
        self.failure = "photo_unavailable" if tools.web_search.image_requested else "no_candidate"
        self.vetting = result.vetting if result else None
        self.leak_retried = bool(result and result.leak_retried)
        if self.vetting is not None:
            self.candidate, self.verdict, self.visual = self.vetting.candidate, self.vetting.verdict, self.vetting.visual
            self.failure = self.vetting.failure
        self.failed = self.candidate is None or self.verdict is None or not self.verdict.ok
        return "generated"

    def screen(self):
        with agent_step_span("check", "tutoring.output_safety") as safety_span:
            review_text = None if self.failed else (
                self.candidate.content if self.visual is None else f"{self.candidate.content}\n{describe(self.visual)}"
            )
            set_observation_payload(safety_span, input={"text": review_text, "skipped": self.failed})
            safety = not self.failed and (
                self.candidate.act == "safety" or self.owner._safety().blocks_output(
                    text=review_text,
                )
            )
            safety_result = "skipped" if self.failed else "blocked" if safety else "pass"
            safety_span.set_attribute("agent.check.result", safety_result)
            set_observation_payload(safety_span, output={"result": safety_result})
        if self.failed:
            return "failed"
        if safety:
            return "unsafe_output"
        if isinstance(self.visual, SearchPhoto):
            from app.infrastructure.storage.object_storage import save_reviewed_photo
            try:
                self.photo_key = save_reviewed_photo(self.invocation.ward_id, self.visual.jpeg)
            except OSError:
                self.failure = "photo_unavailable"
                self.failed = True
                return "failed"
        if self.candidate.act in {"pronounce", "clarify"}:
            return self.candidate.act
        return "work" if self.verdict.effective_work_product else "conversation"

    def pronounce(self):
        outcome = project_lesson(
            self.owner.db, self.invocation, self.candidate.lesson,
            lessons=self.candidate.lessons, content=self.candidate.content,
        )
        outcome.context_snapshot = self.envelope.trace_snapshot()
        record_tutor_turn_result(
            act=self.candidate.act, relation=self.candidate.relation, topic=self.candidate.topic, depth=self.candidate.depth, outcome="shown", reason=None,
            shown=self.candidate.content,
        )
        return outcome

    def clarify(self):
        text = self.candidate.content
        listed = "\n".join(f"{i}. {item}" for i, item in enumerate(self.candidate.candidates, start=1))
        record_tutor_turn_result(
            act=self.candidate.act, relation=self.candidate.relation, topic=self.candidate.topic, depth=self.candidate.depth, outcome="shown", reason=None, shown=text,
        )
        interaction = build_interaction(
            invocation=self.invocation, kind="clarify", text=f"{text}\n{listed}" if listed else text,
            actions=[{"name": "reply", "label": "回复", "command": "clarify_reply", "enabled": True}],
        )
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting",
            next_interaction={**interaction, "status": "needs_input"},
            context_snapshot=self.envelope.trace_snapshot(),
        )

    def open_messages(self):
        self.session, self.tutor = self.owner._ensure_tutor(self.invocation.ward_id, self.session, self.tutor, self.content)
        self.refs = [f"tutoring_session:{self.tutor.id}"]
        self.ward_msg = self.owner._ward_message(self.tutor, self.content)

    def fallback(self):
        self.open_messages()
        text = fallback_text(self.failure, self.vetting.leak_reason if self.vetting else None)
        record_tutor_turn_result(
            act=self.candidate.act if self.candidate else None, relation=self.candidate.relation if self.candidate else None,
            leak_retried=self.leak_retried, outcome="fallback", reason=self.failure or "exit_check", shown=text,
            shape_flags=self.vetting.shape_flags if self.vetting else None,
        )
        return self.owner._reply(
            self.invocation, self.tutor, self.refs, self.envelope, text=text, blocked=False,
            permit=self.permit, problem_status=self.problem_row.status if self.problem_row else None,
        )

    def blocked_output(self):
        self.open_messages()
        record_tutor_turn_result(
            act=self.candidate.act, relation=self.candidate.relation, outcome="blocked", reason="safety", shown=SAFE_TEXT,
        )
        return self.owner._reply(
            self.invocation, self.tutor, self.refs, self.envelope, text=SAFE_TEXT, blocked=True,
            permit=self.permit, problem_status=self.problem_row.status if self.problem_row else None,
        )

    def apply_work(self):
        self.open_messages()
        planned_blueprint = None
        planned_group = None
        target_dossier_id = self.active_dossier.dossier_id if self.active_dossier is not None else None
        if self.candidate.relation == "new" and self.problem_row is not None:
            target_dossier_id = None
        if (
            self.candidate.relation in {"new", "subproblem"}
            and (self.candidate.depth or "reasoning") == "reasoning"
            and (self.problem_row is None or self.candidate.relation != "same" or self.problem_row.last_turn_id != self.invocation.turn_id)
        ):
            from app.contexts.tutoring.domain.blueprint import (
                ProblemGroupContext,
                VerifiedPriorConclusion,
            )

            prior_group_vo = (
                ProblemGroupContext.from_dict(self.problem_row.group_context)
                if self.problem_row is not None and self.problem_row.group_context
                else None
            )
            if self.candidate.relation == "subproblem":
                base_group = prior_group_vo or ProblemGroupContext(
                    shared_stem_ref=f"group_{self.problem_row.id}" if self.problem_row is not None else f"group_{self.tutor.id}",
                    shared_stem_summary=(self.problem_row.summary if self.problem_row is not None else self.content)[:500],
                    subproblem_label="(1)",
                )
                prior_conc = (
                    VerifiedPriorConclusion(
                        subproblem_label=base_group.subproblem_label or "(prev)",
                        conclusion=self.candidate.work.verified_prior_conclusion,
                    )
                    if self.candidate.work and self.candidate.work.verified_prior_conclusion
                    else None
                )
                prior_group_vo = base_group.advance_to_subproblem(
                    next_label=(self.candidate.work.subproblem_label if self.candidate.work else None) or "(next)",
                    verified_conclusion=prior_conc,
                )
                # Subproblems on a dossier-backed stem share the parent dossier!
                if target_dossier_id is None and self.problem_row is not None and self.problem_row.dossier_id:
                    target_dossier_id = self.problem_row.dossier_id
            else:
                prior_group_vo = None

            # If explicit legacy `blueprint_planner` was injected in unit tests (and no async dossier requested),
            # preserve transitional synchronous fallback; otherwise async `ProblemDossier` owns solving!
            if target_dossier_id is None and self.owner.blueprint_planner is not None:
                from app.application.workflows.blueprint_planner import (
                    build_verified_blueprint_and_group,
                )

                planned_blueprint, planned_group = build_verified_blueprint_and_group(
                    self.owner.blueprint_planner,
                    self.owner.math_engine,
                    content=self.content,
                    images=self.all_authorized_images,
                    prior_group=prior_group_vo,
                    grade_stage=self.grade_stage,
                )
            else:
                planned_group = prior_group_vo
                report = self.candidate.image_review
                is_worksheet_batch_check = bool(
                    report is not None
                    and report.conclusion != "not_checking"
                    and len(report.questions) >= 2
                )
                if (
                    target_dossier_id is None
                    and not is_worksheet_batch_check
                    and self.owner._dossier_mode_enabled()
                ):
                    from app.application.commands.problem_solving import (
                        RequestSolveCommand,
                    )

                    enqueue_cb = self.owner.dossier_enqueue_fn
                    defer_until_commit = False
                    if enqueue_cb is None:
                        from app.workers.solving_tasks import enqueue_solve_dossier

                        enqueue_cb = lambda did, _imgs=None: enqueue_solve_dossier(
                            did, attachment_keys=self.selected_attachment_keys
                        )
                        defer_until_commit = True
                    created_dos = RequestSolveCommand(
                        self.owner.db,
                        enqueue_fn=enqueue_cb,
                        defer_until_commit=defer_until_commit,
                    ).execute(
                        ward_id=self.invocation.ward_id,
                        text=self.content,
                        images=self.all_authorized_images,
                    )
                    target_dossier_id = created_dos.dossier_id

        self.problem_status, self.hint_index, self.attempted, self.evidence_problem_id = self.owner._apply_problem(
            self.tutor, self.problem_row, self.candidate, self.verdict, self.invocation, has_work_input=bool(self.content.strip() or self.images),
            summary=self.content, planned_blueprint=planned_blueprint, planned_group=planned_group,
            dossier_id=target_dossier_id,
        )
        return "applied"

    def answer(self):
        if self.ward_msg is None:
            self.open_messages()
        text = self.candidate.content
        work = self.verdict.effective_work_product
        # A redirect already takes the Ward back to the task; a second reminder would repeat it.
        remind = self.task_active and not work and self.candidate.act != "redirect"
        if remind and REMINDER not in text:
            text = f"{text.rstrip()}\n{REMINDER}"

        answer_protected = self.verdict.answer_protected
        if self.evidence_problem_id:
            self.ward_msg.problem_id = self.evidence_problem_id
            self.ward_msg.evidence_kind = "attempt" if self.attempted else "question"
        message = TutoringMessage(
            tutoring_session_id=self.tutor.id, role="assistant", content=text,
            problem_id=self.evidence_problem_id,
            evidence_kind=("guide" if self.hint_index is not None else "reply") if self.evidence_problem_id else None,
        )
        self.owner.db.add(message)
        self.owner.db.flush()
        payload = {"tutoring_session_id": self.tutor.id, "study_session_id": self.session.id}
        if self.attempted:
            publish_learning_fact(
                self.owner.db, ward_id=self.session.ward_id, event_type="tutoring.attempt_recorded",
                source_type="tutoring_message", source_id=self.ward_msg.id, source="ward", visibility="ward",
                payload={**payload, "directive": self.directive},
            )
        if work and self.hint_index is not None:
            publish_learning_fact(
                self.owner.db, ward_id=self.session.ward_id, event_type="tutoring.hint_given",
                source_type="tutoring_message", source_id=message.id, source="system",
                payload={**payload, "hint_index": self.hint_index},
            )
        if self.candidate.topic == "spontaneous_curiosity":
            publish_learning_fact(
                self.owner.db, ward_id=self.session.ward_id, event_type="tutoring.curiosity_observed",
                source_type="tutoring_message", source_id=self.ward_msg.id, source="ward", visibility="ward", payload=payload,
            )
        record_tutor_turn_result(
            act=self.candidate.act, relation=self.candidate.relation, topic=self.candidate.topic, depth=self.candidate.depth,
            student_move=self.candidate.work.student_move if self.candidate.work else None, leak_retried=self.leak_retried,
            outcome="shown", reason=None, shown=text,
            visual_kind=self.visual.kind if self.visual else None, visual_dropped=self.vetting.visual_dropped if self.vetting else None,
            shape_flags=self.vetting.shape_flags if self.vetting else None,
        )
        next_interaction = {
            "status": "needs_input", "content": text, "act": self.candidate.act,
            "hint_index": self.hint_index, "problem_status": self.problem_status,
            "answer_protected": answer_protected, "safety_blocked": False,
            "return_to_task": remind, "model": components.model_for("tutoring.turn"), "model_fallback": False,
        }
        if self.visual is not None:
            # 只有通过全部检查的图才投影；kind 由 Application 决定，模型从不返回 kind。
            next_interaction.update(build_interaction(
                invocation=self.invocation, kind="text_visual", text=text,
                visual=self.visual.model_dump(exclude_none=True),
            ))
        return WorkflowOutcome(
            run_status="waiting_for_ward", outcome_type="waiting", context_refs=self.refs,
            next_interaction=next_interaction,
            reviewed_photo_keys=[self.photo_key] if isinstance(self.visual, SearchPhoto) else [],
            context_snapshot=self.envelope.trace_snapshot(),
        )
