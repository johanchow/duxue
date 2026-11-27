"""Authenticated Adult MentorCourseware API (/guardian/courseware/*).

Strictly isolated from Ward threads, TutoringSession, and Memory facts.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.deps import Principal, current_guardian
from app.application.commands.mentor_courseware import (
    CoursewareForbiddenError,
    CoursewareNotFoundError,
    CreateMentorCoursewareInput,
    MentorCoursewareCommandService,
    MoveCoursewareCursorInput,
    RequestCoursewareRevisionInput,
)
from app.application.process_managers.mentor_courseware_orchestrator import (
    MentorCoursewareOrchestrator,
)
from app.application.queries.mentor_courseware import MentorCoursewareQueryService
from app.application.workflows.guardian_experience import owns_image
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    CoursewareDomainError,
    CoursewareInvariantViolationError,
)
from app.infrastructure.ai.mentor_courseware_adapters import (
    ComponentSceneMediaRenderer,
    ModelDirectorAdapter,
    ModelPedagogicalJudgeAdapter,
    ProblemSolvingAclAdapter,
)
from app.infrastructure.ai.tutoring_safety import LocalSafetyScreening
from app.infrastructure.persistence.mentor_courseware_store import (
    build_default_courseware_stores,
)
from app.infrastructure.storage.object_storage import storage

router = APIRouter(prefix="/guardian/courseware", tags=["guardian-courseware"])

_safety = LocalSafetyScreening()
from app.infrastructure.persistence.pg_courseware import PgCoursewareRepository

_legacy_repo, _status_store = build_default_courseware_stores()
_repo = PgCoursewareRepository(legacy=_legacy_repo)
_commands = MentorCoursewareCommandService(_repo)
_queries = MentorCoursewareQueryService(_repo, _status_store)
_orchestrator = MentorCoursewareOrchestrator(
    repo=_repo,
    commands=_commands,
    status_store=_status_store,
    verifier=ProblemSolvingAclAdapter(),
    director=ModelDirectorAdapter(),
    judge=ModelPedagogicalJudgeAdapter(),
    renderer=ComponentSceneMediaRenderer(),
    safety=_safety,
)


def get_courseware_services():
    return _commands, _queries, _orchestrator


class CreateCoursewareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    prompt_text: str = Field(default="", max_length=2400)
    attachment_keys: list[str] = Field(default_factory=list, max_length=4)
    target_grade_hint: str | None = Field(default=None, max_length=64)
    media_profile: Literal["interactive", "narrated"] = "interactive"

    @model_validator(mode="after")
    def _nonempty(self):
        self.prompt_text = self.prompt_text.strip()
        if not self.prompt_text and not self.attachment_keys:
            raise ValueError("a question or image is required")
        return self


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=1200)
    base_version_no: int = Field(ge=1)
    expected_state_revision: int = Field(ge=1)
    target_step_id: str | None = Field(default=None, max_length=64)
    allow_unverified_override: bool = False


class CursorMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=1, max_length=128)
    expected_state_revision: int = Field(ge=1)


def _translate_error(exc: CoursewareDomainError) -> HTTPException:
    if isinstance(exc, CoursewareNotFoundError):
        return HTTPException(404, {"code": exc.code, "message": exc.message})
    if isinstance(exc, CoursewareForbiddenError):
        return HTTPException(403, {"code": exc.code, "message": exc.message})
    if isinstance(exc, CoursewareConflictError):
        return HTTPException(409, {"code": exc.code, "message": exc.message})
    if isinstance(exc, CoursewareInvariantViolationError):
        return HTTPException(422, {"code": exc.code, "message": exc.message})
    return HTTPException(400, {"code": exc.code, "message": exc.message})


@router.post("", status_code=202)
def create_courseware(
    body: CreateCoursewareRequest,
    background_tasks: BackgroundTasks,
    principal: Annotated[Principal, Depends(current_guardian)],
    services: Annotated[tuple, Depends(get_courseware_services)],
):
    commands, _, orchestrator = services
    if body.prompt_text and _safety.blocks_input(text=body.prompt_text):
        raise HTTPException(400, {"code": "input_safety_blocked", "message": "输入内容未通过安全检查"})
    if any(not owns_image(principal.user_id, key) or not storage.exists(key) for key in body.attachment_keys):
        raise HTTPException(400, {"code": "invalid_attachment", "message": "无效的图片附件"})

    try:
        res = commands.create(
            CreateMentorCoursewareInput(
                guardian_id=UUID(principal.user_id),
                command_id=body.command_id,
                prompt_text=body.prompt_text or "请看这张图片，生成分步深度教学课件。",
                attachment_keys=body.attachment_keys,
                target_grade_hint=body.target_grade_hint,
                media_profile=body.media_profile,
            )
        )
    except CoursewareDomainError as exc:
        raise _translate_error(exc) from exc

    if not res.idempotent_replay:
        background_tasks.add_task(orchestrator.run_initial, res.courseware_id)

    return {
        "courseware_id": str(res.courseware_id),
        "status": res.status,
        "state_revision": res.state_revision,
    }


class LibraryMutation(CursorMoveRequest):
    title: str = Field(default="", max_length=80)


@router.get("")
def list_saved(principal: Annotated[Principal, Depends(current_guardian)], cursor: str | None = None):
    try:
        before = None
        if cursor:
            stamp, cid = cursor.split("|")
            before = datetime.fromisoformat(stamp), UUID(cid)
    except ValueError:
        raise HTTPException(422, "分页位置无效") from None
    return _queries.list_saved(UUID(principal.user_id), before)


def _load_photos(keys):
    from io import BytesIO

    from PIL import Image
    photos = []
    thumbnail = None
    for key in keys:
        data = storage.read_limited(key, 12 * 1024 * 1024)
        if not photos:
            with Image.open(BytesIO(data)) as image:
                image.thumbnail((96, 96))
                output = BytesIO()
                image.convert("RGB").save(output, "JPEG", quality=72)
                thumbnail = base64.b64encode(output.getvalue()).decode("ascii")
        photos.append(base64.b64encode(data).decode("ascii"))
    return photos, thumbnail


def change_library(action, cid, body, principal):
    owner = UUID(principal.user_id)
    try:
        _commands.change_library(owner, cid, action, body.command_id, body.title, body.expected_state_revision, _load_photos)
        if action != "delete":
            return _queries.get_view(courseware_id=cid, guardian_id=owner)
    except OSError:
        raise HTTPException(503, {"code": "courseware_asset_unavailable", "message": "暂时无法读取题图，请重试"}) from None
    except CoursewareDomainError as exc:
        if action == "delete" and isinstance(exc, CoursewareNotFoundError):
            return
        raise _translate_error(exc) from exc


@router.post("/{courseware_id}/save")
def save_courseware(courseware_id: UUID, body: LibraryMutation, principal: Annotated[Principal, Depends(current_guardian)]):
    return change_library("save", courseware_id, body, principal)


@router.patch("/{courseware_id}")
def rename_courseware(courseware_id: UUID, body: LibraryMutation, principal: Annotated[Principal, Depends(current_guardian)]):
    return change_library("rename", courseware_id, body, principal)


@router.delete("/{courseware_id}", status_code=204)
def delete_courseware(courseware_id: UUID, body: LibraryMutation, principal: Annotated[Principal, Depends(current_guardian)]):
    change_library("delete", courseware_id, body, principal)


@router.get("/{courseware_id}/photos")
def get_saved_photos(courseware_id: UUID, principal: Annotated[Principal, Depends(current_guardian)]):
    return {"photos": _queries.get_saved_photos(UUID(principal.user_id), courseware_id)}


@router.get("/{courseware_id}")
def get_courseware_view(
    courseware_id: UUID,
    principal: Annotated[Principal, Depends(current_guardian)],
    services: Annotated[tuple, Depends(get_courseware_services)],
):
    _, queries, _ = services
    try:
        return queries.get_view(courseware_id=courseware_id, guardian_id=UUID(principal.user_id))
    except CoursewareDomainError as exc:
        raise _translate_error(exc) from exc


@router.get("/{courseware_id}/status")
def get_courseware_status(
    courseware_id: UUID,
    principal: Annotated[Principal, Depends(current_guardian)],
    services: Annotated[tuple, Depends(get_courseware_services)],
):
    _, queries, _ = services
    try:
        return queries.get_status(courseware_id=courseware_id, guardian_id=UUID(principal.user_id))
    except CoursewareDomainError as exc:
        raise _translate_error(exc) from exc


@router.post("/{courseware_id}/revisions", status_code=202)
def request_revision(
    courseware_id: UUID,
    body: RevisionRequest,
    background_tasks: BackgroundTasks,
    principal: Annotated[Principal, Depends(current_guardian)],
    services: Annotated[tuple, Depends(get_courseware_services)],
):
    commands, _, orchestrator = services
    if _safety.blocks_input(text=body.instruction):
        raise HTTPException(400, {"code": "input_safety_blocked", "message": "修订指令未通过安全检查"})

    try:
        res = commands.request_revision(
            RequestCoursewareRevisionInput(
                guardian_id=UUID(principal.user_id),
                courseware_id=courseware_id,
                command_id=body.command_id,
                instruction=body.instruction,
                base_version_no=body.base_version_no,
                expected_state_revision=body.expected_state_revision,
                target_step_id=body.target_step_id,
                allow_unverified_override=body.allow_unverified_override,
            )
        )
    except CoursewareDomainError as exc:
        raise _translate_error(exc) from exc

    if not res.idempotent_replay:
        background_tasks.add_task(
            orchestrator.run_revision,
            courseware_id=courseware_id,
            revision_id=res.revision_id,
            base_version_no=res.base_version_no,
            started_state_revision=res.started_state_revision,
            instruction=body.instruction,
            target_step_id=body.target_step_id,
            allow_unverified_override=body.allow_unverified_override,
        )

    return {
        "courseware_id": str(res.courseware_id),
        "revision_id": res.revision_id,
        "base_version_no": res.base_version_no,
        "state_revision": res.started_state_revision,
    }


@router.post("/{courseware_id}/undo")
def undo_courseware(
    courseware_id: UUID,
    body: CursorMoveRequest,
    principal: Annotated[Principal, Depends(current_guardian)],
    services: Annotated[tuple, Depends(get_courseware_services)],
):
    commands, queries, _ = services
    try:
        commands.undo(
            MoveCoursewareCursorInput(
                guardian_id=UUID(principal.user_id),
                courseware_id=courseware_id,
                command_id=body.command_id,
                expected_state_revision=body.expected_state_revision,
            )
        )
        return queries.get_view(courseware_id=courseware_id, guardian_id=UUID(principal.user_id))
    except CoursewareDomainError as exc:
        raise _translate_error(exc) from exc


@router.post("/{courseware_id}/redo")
def redo_courseware(
    courseware_id: UUID,
    body: CursorMoveRequest,
    principal: Annotated[Principal, Depends(current_guardian)],
    services: Annotated[tuple, Depends(get_courseware_services)],
):
    commands, queries, _ = services
    try:
        commands.redo(
            MoveCoursewareCursorInput(
                guardian_id=UUID(principal.user_id),
                courseware_id=courseware_id,
                command_id=body.command_id,
                expected_state_revision=body.expected_state_revision,
            )
        )
        return queries.get_view(courseware_id=courseware_id, guardian_id=UUID(principal.user_id))
    except CoursewareDomainError as exc:
        raise _translate_error(exc) from exc
