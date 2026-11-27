"""Tutoring Domain: Adult MentorCourseware aggregate root, immutable versions, and policies.

Pure domain module: zero dependencies on ORM, HTTP, Redis, Celery, or LLM SDKs.
Strictly isolated from Ward `TutoringSession`, `TutorPermitPolicy`, and `Memory` facts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

CoursewareStatus = Literal["drafting", "ready", "failed"]
VerificationStatus = Literal["verified", "unverified_custom", "low_confidence"]
BaselineConfidence = Literal["high", "medium", "low"]
VisualKind = Literal["component_scene", "layered_svg", "math_stage_script"]
PatchOp = Literal["insert", "update", "delete", "split", "replace_method"]

MAX_COURSEWARE_VERSIONS = 20
_VALID_VISUAL_KINDS = frozenset({"component_scene", "layered_svg", "math_stage_script"})
_VALID_VERIFICATION_STATUSES = frozenset({"verified", "unverified_custom", "low_confidence"})


class CoursewareDomainError(Exception):
    """Base domain error for MentorCourseware."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CoursewareConflictError(CoursewareDomainError):
    """Raised on CAS mismatch, concurrent revision lock, or cursor bounds."""


class CoursewareInvariantViolationError(CoursewareDomainError):
    """Raised when a candidate version violates teaching or honesty invariants."""


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


@dataclass(frozen=True)
class VerificationBaseline:
    """Immutable snapshot of ProblemSolving's objective verification baseline."""

    baseline_hash: str
    confidence: BaselineConfidence
    summary_answer: str
    stem_text: str = ""
    subject: str = "general"
    dossier_ref: str | None = None
    approaches: tuple[dict[str, Any], ...] = ()
    final_answers: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        confidence: BaselineConfidence,
        summary_answer: str,
        stem_text: str = "",
        subject: str = "general",
        dossier_ref: str | None = None,
        approaches: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        final_answers: list[str] | tuple[str, ...] = (),
    ) -> VerificationBaseline:
        norm_approaches = tuple(approaches)
        norm_answers = tuple(str(a) for a in final_answers)
        b_hash = _canonical_hash(
            {
                "confidence": confidence,
                "summary_answer": summary_answer.strip(),
                "stem_text": stem_text.strip(),
                "subject": subject.strip(),
                "dossier_ref": dossier_ref,
                "approaches": list(norm_approaches),
                "final_answers": list(norm_answers),
            }
        )
        return cls(
            baseline_hash=b_hash,
            confidence=confidence,
            summary_answer=summary_answer.strip(),
            stem_text=stem_text.strip(),
            subject=subject.strip() or "general",
            dossier_ref=dossier_ref,
            approaches=norm_approaches,
            final_answers=norm_answers,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_hash": self.baseline_hash,
            "confidence": self.confidence,
            "summary_answer": self.summary_answer,
            "stem_text": self.stem_text,
            "subject": self.subject,
            "dossier_ref": self.dossier_ref,
            "approaches": list(self.approaches),
            "final_answers": list(self.final_answers),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VerificationBaseline:
        return cls(
            baseline_hash=str(raw["baseline_hash"]),
            confidence=raw["confidence"],
            summary_answer=str(raw.get("summary_answer") or ""),
            stem_text=str(raw.get("stem_text") or ""),
            subject=str(raw.get("subject") or "general"),
            dossier_ref=raw.get("dossier_ref"),
            approaches=tuple(raw.get("approaches") or ()),
            final_answers=tuple(str(x) for x in (raw.get("final_answers") or ())),
        )


@dataclass(frozen=True)
class VisualSpec:
    """Discriminated visual payload for a courseware step."""

    kind: VisualKind
    payload: dict[str, Any]
    title: str = ""
    alt: str = ""
    runtime_version: str = "1.0"
    min_runtime_version: str = "1.0"
    static_fallback_svg: str | None = None
    static_fallback_text: str | None = None
    highlight_anchors: tuple[str, ...] = ()
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(
                self,
                "content_hash",
                _canonical_hash(
                    {
                        "kind": self.kind,
                        "payload": self.payload,
                        "title": self.title,
                        "alt": self.alt,
                        "runtime_version": self.runtime_version,
                        "static_fallback_svg": self.static_fallback_svg,
                        "static_fallback_text": self.static_fallback_text,
                        "highlight_anchors": list(self.highlight_anchors),
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "payload": self.payload,
            "title": self.title,
            "alt": self.alt,
            "runtime_version": self.runtime_version,
            "min_runtime_version": self.min_runtime_version,
            "static_fallback_svg": self.static_fallback_svg,
            "static_fallback_text": self.static_fallback_text,
            "highlight_anchors": list(self.highlight_anchors),
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VisualSpec:
        return cls(
            kind=raw["kind"],
            payload=dict(raw.get("payload") or {}),
            title=str(raw.get("title") or ""),
            alt=str(raw.get("alt") or ""),
            runtime_version=str(raw.get("runtime_version") or "1.0"),
            min_runtime_version=str(raw.get("min_runtime_version") or "1.0"),
            static_fallback_svg=raw.get("static_fallback_svg"),
            static_fallback_text=raw.get("static_fallback_text"),
            highlight_anchors=tuple(str(a) for a in (raw.get("highlight_anchors") or ())),
            content_hash=str(raw.get("content_hash") or ""),
        )


@dataclass(frozen=True)
class CoursewareStep:
    """Minimal addressable teaching unit with stable step_id."""

    step_id: str
    title: str
    action_what: str
    thinking_why: str | None = None
    pedagogical_role: str | None = None
    visual_spec: VisualSpec | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(
                self,
                "content_hash",
                _canonical_hash(
                    {
                        "step_id": self.step_id,
                        "title": self.title,
                        "action_what": self.action_what,
                        "thinking_why": self.thinking_why,
                        "pedagogical_role": self.pedagogical_role,
                        "visual_hash": self.visual_spec.content_hash if self.visual_spec else None,
                    }
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "action_what": self.action_what,
            "thinking_why": self.thinking_why,
            "pedagogical_role": self.pedagogical_role,
            "visual_spec": self.visual_spec.to_dict() if self.visual_spec else None,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CoursewareStep:
        v = raw.get("visual_spec")
        return cls(
            step_id=str(raw["step_id"]),
            title=str(raw.get("title") or ""),
            action_what=str(raw.get("action_what") or ""),
            thinking_why=raw.get("thinking_why"),
            pedagogical_role=raw.get("pedagogical_role"),
            visual_spec=VisualSpec.from_dict(v) if isinstance(v, dict) else None,
            content_hash=str(raw.get("content_hash") or ""),
        )


@dataclass(frozen=True)
class CoursewareVersion:
    """Immutable snapshot of a published courseware version."""

    version_no: int
    parent_version_no: int | None
    baseline_hash: str
    change_summary: str
    verification_status: VerificationStatus
    steps: tuple[CoursewareStep, ...]
    methodology_key: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_no": self.version_no,
            "parent_version_no": self.parent_version_no,
            "baseline_hash": self.baseline_hash,
            "change_summary": self.change_summary,
            "verification_status": self.verification_status,
            "methodology_key": self.methodology_key,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CoursewareVersion:
        return cls(
            version_no=int(raw["version_no"]),
            parent_version_no=int(raw["parent_version_no"]) if raw.get("parent_version_no") is not None else None,
            baseline_hash=str(raw["baseline_hash"]),
            change_summary=str(raw.get("change_summary") or ""),
            verification_status=raw["verification_status"],
            methodology_key=raw.get("methodology_key"),
            steps=tuple(CoursewareStep.from_dict(s) for s in (raw.get("steps") or ())),
            created_at=str(raw.get("created_at") or datetime.now(timezone.utc).isoformat()),
        )


@dataclass(frozen=True)
class CoursewarePatch:
    """Structured local revision instruction."""

    patch_id: str
    op: PatchOp
    target_step_id: str | None
    requires_reverify: bool
    summary: str
    replacement_steps: tuple[CoursewareStep, ...] = ()


@dataclass(frozen=True)
class ActiveRevisionSlot:
    """Pinned in-flight revision slot used for CAS against concurrent Undo/Redo."""

    revision_id: str
    base_version_no: int
    started_state_revision: int
    instruction: str = ""
    target_step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "base_version_no": self.base_version_no,
            "started_state_revision": self.started_state_revision,
            "instruction": self.instruction,
            "target_step_id": self.target_step_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ActiveRevisionSlot:
        return cls(
            revision_id=str(raw["revision_id"]),
            base_version_no=int(raw["base_version_no"]),
            started_state_revision=int(raw["started_state_revision"]),
            instruction=str(raw.get("instruction") or ""),
            target_step_id=raw.get("target_step_id"),
        )


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    courseware_id: str
    payload: dict[str, Any]
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CoursewareInvariantPolicy:
    """Stateless domain service validating teaching structure & verification honesty."""

    @staticmethod
    def validate(
        candidate: CoursewareVersion,
        *,
        baseline: VerificationBaseline | None,
        requires_reverify: bool,
        reverify_passed: bool | None,
        allow_unverified_override: bool,
        allow_generated_js: bool = False,
    ) -> VerificationStatus:
        if baseline is None:
            raise CoursewareInvariantViolationError("missing_baseline", "发布课件版本前必须绑定不可变核验基线")
        if candidate.baseline_hash != baseline.baseline_hash:
            raise CoursewareInvariantViolationError("baseline_hash_mismatch", "候选版本的 baseline_hash 与目标核验基线不一致")
        if not candidate.steps:
            raise CoursewareInvariantViolationError("empty_steps", "课件至少包含一个教学步骤")

        seen_ids: set[str] = set()
        for step in candidate.steps:
            sid = step.step_id.strip()
            if not sid:
                raise CoursewareInvariantViolationError("empty_step_id", "教学步骤缺少有效 step_id")
            if sid in seen_ids:
                raise CoursewareInvariantViolationError("duplicate_step_id", f"重复的 step_id: {sid}")
            seen_ids.add(sid)
            if not step.action_what.strip():
                raise CoursewareInvariantViolationError("empty_step_body", f"步骤 {sid} 缺少正文讲解 action_what")
            if step.visual_spec is not None:
                CoursewareInvariantPolicy._validate_visual(step.visual_spec, allow_generated_js=allow_generated_js)

        if candidate.verification_status not in _VALID_VERIFICATION_STATUSES:
            raise CoursewareInvariantViolationError("invalid_verification_status", "非法的 verification_status")

        # Verification honesty rule
        effective_status: VerificationStatus = candidate.verification_status
        if requires_reverify:
            if reverify_passed is True:
                effective_status = "verified" if baseline.confidence != "low" else "low_confidence"
            else:
                if not allow_unverified_override:
                    raise CoursewareInvariantViolationError(
                        "reverify_failed",
                        "确定性引擎复核未通过，禁止发布为已核验版本；需用户显式确认自定义草稿后方可继续",
                    )
                effective_status = "unverified_custom"
        else:
            if baseline.confidence == "low" and effective_status == "verified":
                effective_status = "low_confidence"

        return effective_status

    @staticmethod
    def _validate_visual(visual: VisualSpec, *, allow_generated_js: bool) -> None:
        if visual.kind not in _VALID_VISUAL_KINDS:
            raise CoursewareInvariantViolationError("invalid_visual_kind", f"不支持的图型: {visual.kind}")
        if visual.kind == "math_stage_script" and not allow_generated_js:
            raise CoursewareInvariantViolationError("generated_js_disabled", "P0-1 尚未开放模型生成 JS 路径")
        if visual.kind == "component_scene":
            comp = visual.payload.get("component")
            if not isinstance(comp, str) or not comp.strip():
                raise CoursewareInvariantViolationError("missing_component_name", "component_scene 缺少 component 名称")
            if not visual.static_fallback_text and not visual.static_fallback_svg:
                raise CoursewareInvariantViolationError("missing_static_fallback", "动态组件必须附带已审核静态降级图文")


class CoursewareVersionPolicy:
    """Stateless domain service governing immutable version stack & Undo/Redo bounds."""

    @staticmethod
    def append_version(
        versions: list[CoursewareVersion],
        cursor: int,
        next_version_no: int,
        new_version: CoursewareVersion,
        *,
        max_versions: int = MAX_COURSEWARE_VERSIONS,
    ) -> tuple[list[CoursewareVersion], int, int]:
        if cursor >= 0 and cursor < len(versions) - 1:
            trimmed = list(versions[: cursor + 1])
        else:
            trimmed = list(versions)
        if len(trimmed) >= max_versions:
            raise CoursewareConflictError("version_limit_exceeded", f"单份课件版本数已达上限 {max_versions}")

        parent_no = trimmed[cursor].version_no if (cursor >= 0 and trimmed) else None
        stamped = CoursewareVersion(
            version_no=next_version_no,
            parent_version_no=parent_no,
            baseline_hash=new_version.baseline_hash,
            change_summary=new_version.change_summary,
            verification_status=new_version.verification_status,
            steps=new_version.steps,
            methodology_key=new_version.methodology_key,
            created_at=new_version.created_at,
        )
        trimmed.append(stamped)
        return trimmed, len(trimmed) - 1, next_version_no + 1

    @staticmethod
    def undo(versions: list[CoursewareVersion], cursor: int) -> int:
        if not versions or cursor <= 0:
            raise CoursewareConflictError("cursor_out_of_bounds", "当前已在最早版本，无法继续撤销")
        return cursor - 1

    @staticmethod
    def redo(versions: list[CoursewareVersion], cursor: int) -> int:
        if not versions or cursor >= len(versions) - 1:
            raise CoursewareConflictError("cursor_out_of_bounds", "当前已在最新版本，无法继续重做")
        return cursor + 1


class MentorCourseware:
    """Aggregate Root for an adult mentor's versioned interactive courseware."""

    def __init__(
        self,
        *,
        courseware_id: UUID,
        guardian_id: UUID,
        prompt_text: str,
        attachment_keys: tuple[str, ...] = (),
        target_grade_hint: str | None = None,
        status: CoursewareStatus = "drafting",
        cursor: int = -1,
        state_revision: int = 1,
        next_version_no: int = 1,
        baselines: dict[str, VerificationBaseline] | None = None,
        pending_baseline_hash: str | None = None,
        versions: list[CoursewareVersion] | None = None,
        active_revision: ActiveRevisionSlot | None = None,
        failure_reason: str | None = None,
        degraded_text: str | None = None,
        processed_command_ids: dict[str, dict[str, Any]] | None = None,
        created_at: str | None = None,
        retention_status: str = "temporary",
        title: str = "",
        saved_at: str | None = None,
    ) -> None:
        self.courseware_id = courseware_id
        self.guardian_id = guardian_id
        self.prompt_text = prompt_text
        self.attachment_keys = attachment_keys
        self.target_grade_hint = target_grade_hint
        self.status: CoursewareStatus = status
        self.cursor = cursor
        self.state_revision = state_revision
        self.next_version_no = next_version_no
        self.baselines: dict[str, VerificationBaseline] = dict(baselines or {})
        self.pending_baseline_hash = pending_baseline_hash
        self.versions: list[CoursewareVersion] = list(versions or [])
        self.active_revision: ActiveRevisionSlot | None = active_revision
        self.failure_reason = failure_reason
        self.degraded_text = degraded_text
        self.processed_command_ids: dict[str, dict[str, Any]] = dict(processed_command_ids or {})
        self.retention_status = retention_status
        self.title = title
        self.thumbnail = None
        self.saved_at = saved_at
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.domain_events: list[DomainEvent] = []

    @classmethod
    def create(
        cls,
        *,
        guardian_id: UUID,
        prompt_text: str,
        attachment_keys: list[str] | tuple[str, ...] = (),
        target_grade_hint: str | None = None,
        courseware_id: UUID | None = None,
    ) -> MentorCourseware:
        cid = courseware_id or uuid4()
        agg = cls(
            courseware_id=cid,
            guardian_id=guardian_id,
            prompt_text=prompt_text.strip(),
            attachment_keys=tuple(attachment_keys),
            target_grade_hint=target_grade_hint,
        )
        agg.domain_events.append(
            DomainEvent(
                event_type="MentorCoursewareCreated",
                courseware_id=str(cid),
                payload={"guardian_id": str(guardian_id)},
            )
        )
        return agg

    @property
    def current_version(self) -> CoursewareVersion | None:
        if 0 <= self.cursor < len(self.versions):
            return self.versions[self.cursor]
        return None

    @property
    def current_baseline(self) -> VerificationBaseline | None:
        cur = self.current_version
        if cur is not None:
            return self.baselines.get(cur.baseline_hash)
        if self.pending_baseline_hash:
            return self.baselines.get(self.pending_baseline_hash)
        return None

    def baseline_for_version(self, version_no: int) -> VerificationBaseline | None:
        for v in self.versions:
            if v.version_no == version_no:
                return self.baselines.get(v.baseline_hash)
        return None

    def attach_baseline(self, baseline: VerificationBaseline) -> bool:
        """Attach an immutable verification baseline (idempotent by baseline_hash)."""
        if baseline.baseline_hash in self.baselines:
            if self.pending_baseline_hash is None and not self.versions:
                self.pending_baseline_hash = baseline.baseline_hash
            return False
        self.baselines[baseline.baseline_hash] = baseline
        if not self.versions:
            self.pending_baseline_hash = baseline.baseline_hash
        self.state_revision += 1
        self.domain_events.append(
            DomainEvent(
                event_type="VerificationBaselineAttached",
                courseware_id=str(self.courseware_id),
                payload={"baseline_hash": baseline.baseline_hash, "confidence": baseline.confidence},
            )
        )
        return True

    def begin_revision(
        self,
        *,
        revision_id: str,
        base_version_no: int,
        expected_state_revision: int,
        instruction: str,
        target_step_id: str | None = None,
    ) -> ActiveRevisionSlot:
        if self.status != "ready" or self.current_version is None:
            raise CoursewareConflictError("courseware_not_ready", "课件尚未就绪，暂不能发起修订")
        if self.active_revision is not None:
            raise CoursewareConflictError("revision_in_progress", "当前已有进行中的修订任务，请稍候或先撤销切换版本")
        if expected_state_revision != self.state_revision:
            raise CoursewareConflictError("stale_state_revision", "课件状态已更新，请刷新后重试")
        if base_version_no != self.current_version.version_no:
            raise CoursewareConflictError("revision_base_changed", "修订依据版本已变化，请基于当前版本重新发起")

        self.state_revision += 1
        slot = ActiveRevisionSlot(
            revision_id=revision_id,
            base_version_no=base_version_no,
            started_state_revision=self.state_revision,
            instruction=instruction.strip(),
            target_step_id=target_step_id,
        )
        self.active_revision = slot
        self.domain_events.append(
            DomainEvent(
                event_type="CoursewareRevisionRequested",
                courseware_id=str(self.courseware_id),
                payload={
                    "revision_id": revision_id,
                    "base_version_no": base_version_no,
                    "state_revision": self.state_revision,
                },
            )
        )
        return slot

    def publish_version(
        self,
        candidate: CoursewareVersion,
        *,
        revision_id: str | None,
        base_version_no: int | None,
        expected_state_revision: int,
        requires_reverify: bool,
        reverify_passed: bool | None,
        allow_unverified_override: bool = False,
        new_baseline: VerificationBaseline | None = None,
        allow_generated_js: bool = False,
    ) -> CoursewareVersion:
        is_initial = revision_id is None
        if is_initial:
            if self.status != "drafting" or self.versions:
                raise CoursewareConflictError("initial_already_published", "初版课件已发布，不能重复发布 v1")
            if expected_state_revision != self.state_revision:
                raise CoursewareConflictError("revision_base_changed", "初版发布时聚合状态已变更")
        else:
            slot = self.active_revision
            if (
                slot is None
                or slot.revision_id != revision_id
                or slot.base_version_no != base_version_no
                or slot.started_state_revision != expected_state_revision
                or self.state_revision != expected_state_revision
            ):
                if slot is not None and slot.revision_id == revision_id:
                    self.active_revision = None
                raise CoursewareConflictError(
                    "revision_base_changed",
                    "修订期间课件版本或状态已变化，拒绝激活迟到修订结果",
                )

        if new_baseline is not None and new_baseline.baseline_hash not in self.baselines:
            self.baselines[new_baseline.baseline_hash] = new_baseline

        baseline = self.baselines.get(candidate.baseline_hash)
        effective_status = CoursewareInvariantPolicy.validate(
            candidate,
            baseline=baseline,
            requires_reverify=requires_reverify,
            reverify_passed=reverify_passed,
            allow_unverified_override=allow_unverified_override,
            allow_generated_js=allow_generated_js,
        )

        normalized_candidate = CoursewareVersion(
            version_no=candidate.version_no,
            parent_version_no=candidate.parent_version_no,
            baseline_hash=candidate.baseline_hash,
            change_summary=candidate.change_summary,
            verification_status=effective_status,
            steps=candidate.steps,
            methodology_key=candidate.methodology_key,
            created_at=candidate.created_at,
        )
        new_versions, new_cursor, next_vno = CoursewareVersionPolicy.append_version(
            self.versions,
            self.cursor,
            self.next_version_no,
            normalized_candidate,
        )
        self.versions = new_versions
        self.cursor = new_cursor
        self.next_version_no = next_vno
        self.status = "ready"
        self.active_revision = None
        self.failure_reason = None
        self.state_revision += 1

        published = self.versions[self.cursor]
        self.domain_events.append(
            DomainEvent(
                event_type="CoursewareVersionPublished",
                courseware_id=str(self.courseware_id),
                payload={
                    "version_no": published.version_no,
                    "baseline_hash": published.baseline_hash,
                    "verification_status": published.verification_status,
                    "state_revision": self.state_revision,
                },
            )
        )
        return published

    def undo(self, *, expected_state_revision: int) -> CoursewareVersion:
        if expected_state_revision != self.state_revision:
            raise CoursewareConflictError("stale_state_revision", "课件状态已变更，请刷新后再撤销")
        new_cursor = CoursewareVersionPolicy.undo(self.versions, self.cursor)
        discarded = self.active_revision.revision_id if self.active_revision else None
        self.cursor = new_cursor
        # Immediately abandon any in-flight revision and free slot per confirmed UX rule
        self.active_revision = None
        self.state_revision += 1
        self.domain_events.append(
            DomainEvent(
                event_type="CoursewareCursorMoved",
                courseware_id=str(self.courseware_id),
                payload={
                    "op": "undo",
                    "cursor": self.cursor,
                    "version_no": self.versions[self.cursor].version_no,
                    "discarded_revision_id": discarded,
                    "state_revision": self.state_revision,
                },
            )
        )
        return self.versions[self.cursor]

    def redo(self, *, expected_state_revision: int) -> CoursewareVersion:
        if expected_state_revision != self.state_revision:
            raise CoursewareConflictError("stale_state_revision", "课件状态已变更，请刷新后再重做")
        new_cursor = CoursewareVersionPolicy.redo(self.versions, self.cursor)
        discarded = self.active_revision.revision_id if self.active_revision else None
        self.cursor = new_cursor
        self.active_revision = None
        self.state_revision += 1
        self.domain_events.append(
            DomainEvent(
                event_type="CoursewareCursorMoved",
                courseware_id=str(self.courseware_id),
                payload={
                    "op": "redo",
                    "cursor": self.cursor,
                    "version_no": self.versions[self.cursor].version_no,
                    "discarded_revision_id": discarded,
                    "state_revision": self.state_revision,
                },
            )
        )
        return self.versions[self.cursor]

    def mark_failed(
        self,
        *,
        reason_code: str,
        revision_id: str | None = None,
        degraded_text: str | None = None,
    ) -> None:
        if revision_id is not None:
            if self.active_revision is not None and self.active_revision.revision_id == revision_id:
                self.active_revision = None
                self.state_revision += 1
        else:
            if self.status == "drafting":
                self.status = "failed"
                self.failure_reason = reason_code
                self.degraded_text = degraded_text
                self.state_revision += 1
        self.domain_events.append(
            DomainEvent(
                event_type="CoursewareProductionFailed",
                courseware_id=str(self.courseware_id),
                payload={"reason_code": reason_code, "revision_id": revision_id},
            )
        )

    def change_retention(self, action: str, title: str, expected_revision: int) -> None:
        if expected_revision != self.state_revision:
            raise CoursewareConflictError("revision_base_changed", "课件已更新，请刷新")
        if action == "save" and self.retention_status == "temporary":
            if self.status != "ready" or self.active_revision:
                raise CoursewareConflictError("courseware_busy", "请等待课件制作完成")
            self.title = (self.current_baseline.stem_text if self.current_baseline else "")[:80] or self.prompt_text[:80] or "导师课件"
            self.saved_at = datetime.now(timezone.utc).isoformat()
            self.retention_status = "saved"
        elif action == "rename" and self.retention_status == "saved" and 0 < len(title.strip()) <= 80:
            self.title = title.strip()
        elif action == "delete" and self.retention_status == "saved":
            self.retention_status = "deleted"
            self.active_revision = None
        else:
            raise CoursewareConflictError("invalid_retention_change", "当前课件无法执行此操作")
        self.state_revision += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "courseware_id": str(self.courseware_id),
            "guardian_id": str(self.guardian_id),
            "prompt_text": self.prompt_text,
            "attachment_keys": list(self.attachment_keys),
            "target_grade_hint": self.target_grade_hint,
            "status": self.status,
            "cursor": self.cursor,
            "state_revision": self.state_revision,
            "next_version_no": self.next_version_no,
            "baselines": {k: v.to_dict() for k, v in self.baselines.items()},
            "pending_baseline_hash": self.pending_baseline_hash,
            "versions": [v.to_dict() for v in self.versions],
            "active_revision": self.active_revision.to_dict() if self.active_revision else None,
            "failure_reason": self.failure_reason,
            "degraded_text": self.degraded_text,
            "processed_command_ids": self.processed_command_ids,
            "created_at": self.created_at,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "subject": self.current_baseline.subject if self.current_baseline else None,
            "retention_status": self.retention_status,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MentorCourseware:
        baselines = {
            k: VerificationBaseline.from_dict(v)
            for k, v in (raw.get("baselines") or {}).items()
        }
        active_raw = raw.get("active_revision")
        result = cls(
            courseware_id=UUID(str(raw["courseware_id"])),
            guardian_id=UUID(str(raw["guardian_id"])),
            prompt_text=str(raw.get("prompt_text") or ""),
            attachment_keys=tuple(raw.get("attachment_keys") or ()),
            target_grade_hint=raw.get("target_grade_hint"),
            status=raw.get("status", "drafting"),
            cursor=int(raw.get("cursor", -1)),
            state_revision=int(raw.get("state_revision", 1)),
            next_version_no=int(raw.get("next_version_no", 1)),
            baselines=baselines,
            pending_baseline_hash=raw.get("pending_baseline_hash"),
            versions=[CoursewareVersion.from_dict(v) for v in (raw.get("versions") or ())],
            active_revision=ActiveRevisionSlot.from_dict(active_raw) if isinstance(active_raw, dict) else None,
            failure_reason=raw.get("failure_reason"),
            degraded_text=raw.get("degraded_text"),
            processed_command_ids=dict(raw.get("processed_command_ids") or {}),
            created_at=raw.get("created_at"), title=raw.get("title", ""),
            saved_at=raw.get("saved_at"), retention_status=raw.get("retention_status", "temporary"),
        )
        result.thumbnail = raw.get("thumbnail")
        return result
