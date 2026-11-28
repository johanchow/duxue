"""Application Commands for Tutoring.MentorCourseware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.application.ports.mentor_courseware import MentorCoursewareRepository
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    CoursewareDomainError,
    CoursewareVersion,
    MentorCourseware,
    VerificationBaseline,
)


class CoursewareNotFoundError(CoursewareDomainError):
    def __init__(self, courseware_id: UUID) -> None:
        super().__init__("courseware_not_found", f"课件 {courseware_id} 不存在或已过期")


class CoursewareForbiddenError(CoursewareDomainError):
    def __init__(self) -> None:
        super().__init__("courseware_forbidden", "无权访问该导师课件")


class CreateMentorCoursewareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guardian_id: UUID
    command_id: str = Field(min_length=1, max_length=128)
    prompt_text: str = Field(default="", max_length=2400)
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)
    target_grade_hint: str | None = Field(default=None, max_length=64)
    media_profile: Literal["interactive", "narrated"] = "interactive"


class RequestCoursewareRevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guardian_id: UUID
    courseware_id: UUID
    command_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=1200)
    base_version_no: int = Field(ge=1)
    expected_state_revision: int = Field(ge=1)
    target_step_id: str | None = Field(default=None, max_length=64)
    allow_unverified_override: bool = False


class MoveCoursewareCursorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    guardian_id: UUID
    courseware_id: UUID
    command_id: str = Field(min_length=1, max_length=128)
    expected_state_revision: int = Field(ge=1)


@dataclass(frozen=True)
class CreateMentorCoursewareResult:
    courseware_id: UUID
    state_revision: int
    status: str
    idempotent_replay: bool = False


@dataclass(frozen=True)
class RequestRevisionResult:
    courseware_id: UUID
    revision_id: str
    base_version_no: int
    started_state_revision: int
    idempotent_replay: bool = False


class MentorCoursewareCommandService:
    """Coordinates authorization, idempotency, and local CAS transactions."""

    def __init__(self, repo: MentorCoursewareRepository) -> None:
        self._repo = repo

    def _load_owned(self, courseware_id: UUID, guardian_id: UUID) -> MentorCourseware:
        cw = self._repo.get(courseware_id)
        if cw is None:
            raise CoursewareNotFoundError(courseware_id)
        if cw.guardian_id != guardian_id:
            raise CoursewareForbiddenError()
        return cw

    def expire_temporary(self):
        return self._repo.expire_temporary()

    def change_library(self, owner, cid, action, command_id, title, expected_revision, load_photos):
        cw = self._load_owned(cid, owner)
        signature = {"action": action, "title": title, "expected": expected_revision}
        prior = cw.processed_command_ids.get(command_id)
        if prior and prior != signature:
            raise CoursewareConflictError("idempotency_payload_mismatch", "请求编号已使用")
        if prior or (action == "save" and cw.retention_status == "saved"):
            return
        cw.change_retention(action, title, expected_revision)
        cw.processed_command_ids[command_id] = signature
        photos = None
        if action == "save":
            photos, cw.thumbnail = load_photos(cw.attachment_keys)
        self._repo.save_cas(cw, expected_state_revision=expected_revision, photos=photos)

    def create(self, cmd: CreateMentorCoursewareInput) -> CreateMentorCoursewareResult:
        existing = self._repo.get_by_create_command(cmd.guardian_id, cmd.command_id)
        if existing is not None:
            if (
                existing.prompt_text != cmd.prompt_text.strip()
                or list(existing.attachment_keys) != list(cmd.attachment_keys)
            ):
                raise CoursewareConflictError("idempotency_payload_mismatch", "重复 command_id 携带了不同请求内容")
            return CreateMentorCoursewareResult(
                courseware_id=existing.courseware_id,
                state_revision=existing.state_revision,
                status=existing.status,
                idempotent_replay=True,
            )

        cw = MentorCourseware.create(
            guardian_id=cmd.guardian_id,
            prompt_text=cmd.prompt_text,
            attachment_keys=cmd.attachment_keys,
            target_grade_hint=cmd.target_grade_hint,
        )
        winner = self._repo.create(cw, command_id=cmd.command_id)
        if winner:
            return CreateMentorCoursewareResult(winner.courseware_id, winner.state_revision, winner.status, True)
        return CreateMentorCoursewareResult(
            courseware_id=cw.courseware_id,
            state_revision=cw.state_revision,
            status=cw.status,
            idempotent_replay=False,
        )

    def attach_baseline(self, *, courseware_id: UUID, baseline: VerificationBaseline) -> MentorCourseware:
        cw = self._repo.get(courseware_id)
        if cw is None:
            raise CoursewareNotFoundError(courseware_id)
        prev_rev = cw.state_revision
        changed = cw.attach_baseline(baseline)
        if changed:
            self._repo.save_cas(cw, expected_state_revision=prev_rev)
        return cw

    def request_revision(self, cmd: RequestCoursewareRevisionInput) -> RequestRevisionResult:
        cw = self._load_owned(cmd.courseware_id, cmd.guardian_id)
        signature = cmd.model_dump(mode="json", exclude={"guardian_id", "courseware_id", "command_id"})
        if cmd.command_id in cw.processed_command_ids:
            saved = cw.processed_command_ids[cmd.command_id]
            if saved.get("op") != "revision" or saved.get("request", signature) != signature:
                raise CoursewareConflictError("idempotency_payload_mismatch", "请求编号已用于其他操作")
            return RequestRevisionResult(
                courseware_id=cw.courseware_id,
                revision_id=str(saved["revision_id"]),
                base_version_no=int(saved["base_version_no"]),
                started_state_revision=int(saved["started_state_revision"]),
                idempotent_replay=True,
            )

        prev_rev = cw.state_revision
        revision_id = str(uuid4())
        slot = cw.begin_revision(
            revision_id=revision_id,
            base_version_no=cmd.base_version_no,
            expected_state_revision=cmd.expected_state_revision,
            instruction=cmd.instruction,
            target_step_id=cmd.target_step_id,
        )
        cw.processed_command_ids[cmd.command_id] = {
            "op": "revision", "request": signature,
            "revision_id": slot.revision_id,
            "base_version_no": slot.base_version_no,
            "started_state_revision": slot.started_state_revision,
        }
        self._repo.save_cas(cw, expected_state_revision=prev_rev)
        return RequestRevisionResult(
            courseware_id=cw.courseware_id,
            revision_id=slot.revision_id,
            base_version_no=slot.base_version_no,
            started_state_revision=slot.started_state_revision,
            idempotent_replay=False,
        )

    def publish_version(
        self,
        *,
        courseware_id: UUID,
        revision_id: str | None,
        base_version_no: int | None,
        expected_state_revision: int,
        candidate_version: CoursewareVersion,
        requires_reverify: bool,
        reverify_passed: bool | None,
        allow_unverified_override: bool = False,
        new_baseline: VerificationBaseline | None = None,
    ) -> CoursewareVersion:
        cw = self._repo.get(courseware_id)
        if cw is None:
            raise CoursewareNotFoundError(courseware_id)
        prev_rev = cw.state_revision
        published = cw.publish_version(
            candidate_version,
            revision_id=revision_id,
            base_version_no=base_version_no,
            expected_state_revision=expected_state_revision,
            requires_reverify=requires_reverify,
            reverify_passed=reverify_passed,
            allow_unverified_override=allow_unverified_override,
            new_baseline=new_baseline,
            allow_generated_js=False,
        )
        self._repo.save_cas(cw, expected_state_revision=prev_rev)
        return published

    def undo(self, cmd: MoveCoursewareCursorInput) -> MentorCourseware:
        cw = self._load_owned(cmd.courseware_id, cmd.guardian_id)
        if cmd.command_id in cw.processed_command_ids:
            receipt = cw.processed_command_ids[cmd.command_id]
            if receipt.get("op") != "undo" or receipt.get("expected", cmd.expected_state_revision) != cmd.expected_state_revision:
                raise CoursewareConflictError("idempotency_payload_mismatch", "请求编号已用于其他操作")
            return cw
        prev_rev = cw.state_revision
        cw.undo(expected_state_revision=cmd.expected_state_revision)
        cw.processed_command_ids[cmd.command_id] = {"op": "undo", "expected": cmd.expected_state_revision, "state_revision": cw.state_revision}
        self._repo.save_cas(cw, expected_state_revision=prev_rev)
        return cw

    def redo(self, cmd: MoveCoursewareCursorInput) -> MentorCourseware:
        cw = self._load_owned(cmd.courseware_id, cmd.guardian_id)
        if cmd.command_id in cw.processed_command_ids:
            receipt = cw.processed_command_ids[cmd.command_id]
            if receipt.get("op") != "redo" or receipt.get("expected", cmd.expected_state_revision) != cmd.expected_state_revision:
                raise CoursewareConflictError("idempotency_payload_mismatch", "请求编号已用于其他操作")
            return cw
        prev_rev = cw.state_revision
        cw.redo(expected_state_revision=cmd.expected_state_revision)
        cw.processed_command_ids[cmd.command_id] = {"op": "redo", "expected": cmd.expected_state_revision, "state_revision": cw.state_revision}
        self._repo.save_cas(cw, expected_state_revision=prev_rev)
        return cw

    def fail_production(
        self,
        *,
        courseware_id: UUID,
        reason_code: str,
        revision_id: str | None = None,
        degraded_text: str | None = None,
    ) -> MentorCourseware:
        cw = self._repo.get(courseware_id)
        if cw is None:
            raise CoursewareNotFoundError(courseware_id)
        prev_rev = cw.state_revision
        cw.mark_failed(reason_code=reason_code, revision_id=revision_id, degraded_text=degraded_text)
        if cw.state_revision != prev_rev:
            self._repo.save_cas(cw, expected_state_revision=prev_rev)
        return cw
