"""Process Manager: MentorCoursewareOrchestrator (cross-domain ProblemSolving -> Tutoring)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.application.commands.mentor_courseware import MentorCoursewareCommandService
from app.application.ports.mentor_courseware import (
    CoursewareMediaRenderPort,
    DirectorDraftResult,
    MentorCoursewareRepository,
    PedagogicalDirectorPort,
    PedagogicalJudgePort,
    ProblemVerificationPort,
    ProductionStage,
    ProductionStatusSnapshot,
    ProductionStatusStore,
)
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    CoursewareInvariantViolationError,
    CoursewareStep,
    CoursewareVersion,
    VerificationBaseline,
)
from app.infrastructure.ai.tutoring_safety import LocalSafetyScreening

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MentorCoursewareOrchestrator:
    """Coordinates out-of-transaction solving, directing, rendering, and judging.

    Never mutates MentorCourseware directly; all state changes go through
    MentorCoursewareCommandService with strict CAS and idempotency.
    """

    def __init__(
        self,
        *,
        repo: MentorCoursewareRepository,
        commands: MentorCoursewareCommandService,
        status_store: ProductionStatusStore,
        verifier: ProblemVerificationPort,
        director: PedagogicalDirectorPort,
        judge: PedagogicalJudgePort,
        renderer: CoursewareMediaRenderPort,
        safety: LocalSafetyScreening | None = None,
    ) -> None:
        self._repo = repo
        self._commands = commands
        self._status = status_store
        self._verifier = verifier
        self._director = director
        self._judge = judge
        self._renderer = renderer
        self._safety = safety or LocalSafetyScreening()

    def _set_stage(
        self,
        courseware_id: UUID,
        stage: ProductionStage,
        message: str,
        *,
        revision_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._status.set_status(
            ProductionStatusSnapshot(
                courseware_id=str(courseware_id),
                stage=stage,
                message=message,
                revision_id=revision_id,
                updated_at=_now_iso(),
                error_code=error_code,
            )
        )

    def _prepare_steps(
        self,
        steps: tuple[CoursewareStep, ...],
        *,
        preserved_by_id: dict[str, CoursewareStep] | None = None,
        target_step_ids: tuple[str, ...] = (),
    ) -> tuple[CoursewareStep, ...]:
        """Validate/prepare visual specs; reuse untouched steps verbatim on revision."""
        targets = set(target_step_ids)
        prepared: list[CoursewareStep] = []
        for step in steps:
            if preserved_by_id and step.step_id in preserved_by_id and targets and step.step_id not in targets:
                prepared.append(preserved_by_id[step.step_id])
                continue
            visual = step.visual_spec
            if visual is not None:
                visual = self._renderer.validate_and_prepare(visual)
            prepared.append(
                CoursewareStep(
                    step_id=step.step_id,
                    title=step.title,
                    action_what=step.action_what,
                    thinking_why=step.thinking_why,
                    pedagogical_role=step.pedagogical_role,
                    visual_spec=visual,
                )
            )
        return tuple(prepared)

    def _check_output_safety(self, steps: tuple[CoursewareStep, ...]) -> bool:
        parts: list[str] = []
        for s in steps:
            parts.append(s.title)
            if s.thinking_why:
                parts.append(s.thinking_why)
            parts.append(s.action_what)
            if s.visual_spec:
                if s.visual_spec.title:
                    parts.append(s.visual_spec.title)
                if s.visual_spec.alt:
                    parts.append(s.visual_spec.alt)
                if s.visual_spec.static_fallback_text:
                    parts.append(s.visual_spec.static_fallback_text)
        joined = "\n".join(parts)
        return not self._safety.blocks_output(text=joined)

    def run_initial(self, courseware_id: UUID) -> None:
        cw = self._repo.get(courseware_id)
        if cw is None or cw.status != "drafting":
            return

        baseline: VerificationBaseline | None = None
        try:
            # Stage 1: ProblemSolving objective truth
            self._set_stage(courseware_id, "solving", "正在解析题面并进行确定性核验...")
            baseline = self._verifier.solve_and_verify(
                prompt_text=cw.prompt_text,
                attachment_keys=cw.attachment_keys,
                guardian_id=cw.guardian_id,
            )
            cw = self._commands.attach_baseline(courseware_id=courseware_id, baseline=baseline)

            # Stage 2: Pedagogical directing
            self._set_stage(courseware_id, "directing", "正在按题型与学情编排教学思路与图示...")
            draft = self._director.draft_initial(
                prompt_text=cw.prompt_text,
                baseline=baseline,
                target_grade_hint=cw.target_grade_hint,
            )

            # Stage 3: Render & validate visual specs
            self._set_stage(courseware_id, "rendering", "正在校验与装配交互组件图示...")
            prepared_steps = self._prepare_steps(draft.steps)
            draft = DirectorDraftResult(
                change_summary=draft.change_summary,
                methodology_key=draft.methodology_key,
                steps=prepared_steps,
                requires_reverify=False,
            )

            # Stage 4: Heterogeneous pedagogical judge (at most 1 bounded repair)
            self._set_stage(courseware_id, "judging", "正在进行独立名师审稿与安全检查...")
            verdict = self._judge.review(prompt_text=cw.prompt_text, baseline=baseline, draft=draft)
            if not verdict.passed and verdict.critique:
                repaired = self._director.draft_revision(
                    current_version=CoursewareVersion(
                        version_no=1,
                        parent_version_no=None,
                        baseline_hash=baseline.baseline_hash,
                        change_summary=draft.change_summary,
                        verification_status="verified" if baseline.confidence != "low" else "low_confidence",
                        methodology_key=draft.methodology_key,
                        steps=draft.steps,
                    ),
                    baseline=baseline,
                    instruction="根据审稿意见补全思考依据或修复图文脱节",
                    critique=verdict.critique,
                )
                repaired_steps = self._prepare_steps(repaired.steps)
                draft = DirectorDraftResult(
                    change_summary=repaired.change_summary or draft.change_summary,
                    methodology_key=repaired.methodology_key or draft.methodology_key,
                    steps=repaired_steps,
                    requires_reverify=False,
                )

            if not self._check_output_safety(draft.steps):
                raise CoursewareInvariantViolationError("output_safety_blocked", "内容未通过安全审核")

            candidate = CoursewareVersion(
                version_no=1,
                parent_version_no=None,
                baseline_hash=baseline.baseline_hash,
                change_summary=draft.change_summary or "初版深度课件",
                verification_status="verified" if baseline.confidence != "low" else "low_confidence",
                methodology_key=draft.methodology_key,
                steps=draft.steps,
            )
            self._commands.publish_version(
                courseware_id=courseware_id,
                revision_id=None,
                base_version_no=None,
                expected_state_revision=cw.state_revision,
                candidate_version=candidate,
                requires_reverify=False,
                reverify_passed=None,
            )
            self._set_stage(courseware_id, "ready", "深度课件已就绪")
        except Exception as exc:
            logger.exception("mentor_courseware initial production failed: %s", courseware_id)
            reason = exc.code if hasattr(exc, "code") else "production_failed"
            degraded = baseline.summary_answer if baseline else None
            try:
                self._commands.fail_production(
                    courseware_id=courseware_id,
                    reason_code=str(reason),
                    degraded_text=degraded,
                )
            except Exception:
                pass
            self._set_stage(courseware_id, "failed", "深度课件生成失败，已保留核验摘要", error_code=str(reason))

    def run_revision(
        self,
        *,
        courseware_id: UUID,
        revision_id: str,
        base_version_no: int,
        started_state_revision: int,
        instruction: str,
        target_step_id: str | None = None,
        allow_unverified_override: bool = False,
    ) -> None:
        cw = self._repo.get(courseware_id)
        if cw is None:
            return

        base_version = next((v for v in cw.versions if v.version_no == base_version_no), None)
        base_baseline = cw.baseline_for_version(base_version_no)
        if base_version is None or base_baseline is None:
            self._commands.fail_production(
                courseware_id=courseware_id, reason_code="revision_base_missing", revision_id=revision_id
            )
            return

        try:
            self._set_stage(courseware_id, "directing", "正在按你的意见局部修订课件...", revision_id=revision_id)
            draft = self._director.draft_revision(
                current_version=base_version,
                baseline=base_baseline,
                instruction=instruction,
                target_step_id=target_step_id,
            )

            preserved_map = {s.step_id: s for s in base_version.steps}
            self._set_stage(courseware_id, "rendering", "正在更新受影响步骤的图示...", revision_id=revision_id)
            prepared_steps = self._prepare_steps(
                draft.steps,
                preserved_by_id=preserved_map,
                target_step_ids=draft.target_step_ids,
            )

            new_baseline: VerificationBaseline | None = None
            target_baseline = base_baseline
            reverify_passed: bool | None = None
            if draft.requires_reverify:
                self._set_stage(courseware_id, "solving", "检测到解法或结论变更，正在重新核验...", revision_id=revision_id)
                reverify_passed, new_baseline, _detail = self._verifier.reverify_revision(
                    baseline=base_baseline,
                    instruction=instruction,
                    draft_steps=prepared_steps,
                )
                if new_baseline is not None:
                    target_baseline = new_baseline

            self._set_stage(courseware_id, "judging", "正在审校修订内容...", revision_id=revision_id)
            if not self._check_output_safety(prepared_steps):
                raise CoursewareInvariantViolationError("output_safety_blocked", "修订内容未通过安全审核")

            candidate = CoursewareVersion(
                version_no=0,
                parent_version_no=base_version_no,
                baseline_hash=target_baseline.baseline_hash,
                change_summary=draft.change_summary or instruction[:40],
                verification_status=(
                    "verified"
                    if (target_baseline.confidence != "low" and (not draft.requires_reverify or reverify_passed))
                    else "low_confidence"
                ),
                methodology_key=draft.methodology_key if draft.methodology_key is not None else base_version.methodology_key,
                steps=prepared_steps,
            )

            self._commands.publish_version(
                courseware_id=courseware_id,
                revision_id=revision_id,
                base_version_no=base_version_no,
                expected_state_revision=started_state_revision,
                candidate_version=candidate,
                requires_reverify=draft.requires_reverify,
                reverify_passed=reverify_passed,
                allow_unverified_override=allow_unverified_override,
                new_baseline=new_baseline,
            )
            self._set_stage(courseware_id, "ready", "局部修订已完成", revision_id=revision_id)
        except CoursewareConflictError as exc:
            if exc.code == "revision_base_changed":
                # Abandoned because user executed Undo/Redo during flight; never clobber
                logger.info("Discarded stale revision %s for courseware %s", revision_id, courseware_id)
                self._set_stage(courseware_id, "ready", "旧修订因版本切换已自动放弃", revision_id=revision_id)
                return
            self._commands.fail_production(
                courseware_id=courseware_id, reason_code=exc.code, revision_id=revision_id
            )
            self._set_stage(courseware_id, "failed", exc.message, revision_id=revision_id, error_code=exc.code)
        except Exception as exc:
            reason = exc.code if hasattr(exc, "code") else "revision_failed"
            logger.exception("mentor_courseware revision failed: %s (%s)", courseware_id, reason)
            try:
                self._commands.fail_production(
                    courseware_id=courseware_id, reason_code=str(reason), revision_id=revision_id
                )
            except Exception:
                pass
            self._set_stage(
                courseware_id,
                "failed",
                getattr(exc, "message", "修订失败，原版本保持不变"),
                revision_id=revision_id,
                error_code=str(reason),
            )
