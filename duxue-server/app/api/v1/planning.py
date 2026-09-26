from pydantic import BaseModel, Field

from app.application.workflows.planning_adapter import planning_today
from app.application.workflows.planning_domain_service import PlanningDomainService
from app.contexts.planning.domain.scheduling import CANCELLED, COMPLETED
from app.infrastructure.persistence.models import PlanDraft as DraftRecord

from .common import *
from .common import _ward_owned, open_session_for_task


class ConfirmDraftRequest(BaseModel):
    draft_id: str
    expected_draft_version: int = Field(ge=1)


router = APIRouter(tags=["planning"])

def _task_intake_wards(db: Session, guardian_id: str) -> list[dict]:
    rows = db.query(Ward).join(GuardianWard, GuardianWard.ward_id == Ward.id).filter(
        GuardianWard.guardian_id == guardian_id,
    ).order_by(Ward.display_name).all()
    return [{"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage} for ward in rows]


def _task_intake_attachments(guardian_id: str, keys: list[str]) -> None:
    prefix = f"guardian/{guardian_id}/task-intake/"
    if any(not key.startswith(prefix) or not storage.exists(key) for key in keys):
        raise HTTPException(400, "invalid task intake attachment")


@router.post("/task-intake/upload-url")
def task_intake_upload_url(body: UploadUrlRequest, request: Request, principal: Principal = Depends(current_guardian)):
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(400, "unsupported image extension")
    if not body.content_type.startswith("image/"):
        raise HTTPException(400, "unsupported image content type")
    key = f"guardian/{principal.user_id}/task-intake/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@router.post("/task-intake/respond")
def respond_to_task_intake(body: TaskIntakeRequest, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    _task_intake_attachments(principal.user_id, body.attachment_keys)
    wards = _task_intake_wards(db, principal.user_id)
    if not wards:
        raise HTTPException(400, "create a ward before sending tasks")
    try:
        return TaskIntakeService().respond(wards=wards, request=body).model_dump(mode="json")
    except TaskIntakeError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/task-intake/confirm", status_code=201)
def confirm_task_intake(body: TaskIntakeConfirm, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    _task_intake_attachments(principal.user_id, body.attachment_keys)
    try:
        for task in body.tasks:
            owned_ward(db, principal.user_id, task.ward_id)
        rows = [Task(ward_id=task.ward_id, title=task.title, details=task.details, due_date=task.due_date) for task in body.tasks]
        db.add_all(rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for key in body.attachment_keys:
        storage.delete(key)
    return {"assignments": [{"id": row.id, "ward_id": row.ward_id, "title": row.title} for row in rows]}


@router.post("/task-intake/cleanup", status_code=204)
def cleanup_task_intake(body: TaskIntakeCleanup, principal: Principal = Depends(current_guardian)):
    _task_intake_attachments(principal.user_id, body.attachment_keys)
    for key in body.attachment_keys:
        storage.delete(key)


@router.post("/wards/{ward_id}/assignments", status_code=201)
def create_assignment(ward_id: str, body: AssignmentCreate, principal: Principal = Depends(current_guardian), db: Session = Depends(get_db)):
    owned_ward(db, principal.user_id, ward_id); row = Task(ward_id=ward_id, **body.model_dump()); db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "title": row.title, "status": row.status, "source": row.source}

@router.get("/wards/{ward_id}/assignments")
def assignments(ward_id: str, principal: Principal = Depends(current_guardian_or_ward), db: Session = Depends(get_db)):
    if principal.role == "ward": _ward_owned(principal, ward_id)
    else: owned_ward(db, principal.user_id, ward_id)
    PlanningDomainService(db).release_unfinished_tasks(ward_id, planning_today())
    db.commit()
    rows = db.query(Task).filter_by(ward_id=ward_id).filter(Task.status.notin_([COMPLETED, CANCELLED])).all()
    return [{"id": x.id, "title": x.title, "details": x.details, "due_date": x.due_date, "status": x.status,
             "session": open_session_for_task(db, task_id=x.id)} for x in rows]


@router.delete("/wards/{ward_id}/assignments/{assignment_id}", status_code=204)
def delete_assignment(ward_id: str, assignment_id: str, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    """Remove a task from the pool. Past schedule slots that only reference it are cleared too."""
    _ward_owned(principal, ward_id)
    PlanningDomainService(db).delete_task(ward_id, assignment_id)
    db.commit()

@router.put("/wards/{ward_id}/plans/{plan_date}")
def save_plan(ward_id: str, plan_date: date, body: PlanDraft, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if body.plan_date != plan_date:
        raise HTTPException(400, "date mismatch")
    service = PlanningDomainService(db)
    items = []
    for raw in body.items:
        item = dict(raw)
        item['new_task'] = not bool(item.get('assignment_id'))
        items.append(item)
    try:
        draft = service.save_draft(ward_id, plan_date, items)
        view = service.plan_draft_view(ward_id, draft.id)
        db.commit()
        return {"id": draft.id, "status": draft.status, **view}
    except Exception:
        db.rollback()
        raise


@router.post("/wards/{ward_id}/plans/{plan_date}/confirm")
def confirm_plan(ward_id: str, plan_date: date, body: ConfirmDraftRequest | None = None,
                 principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if body is None:
        raise HTTPException(409, "请重新审阅草稿并提交 draft_id 与 expected_draft_version")
    draft = db.get(DraftRecord, body.draft_id)
    if draft is None or draft.ward_id != ward_id or draft.plan_date != plan_date:
        raise HTTPException(404, "计划草稿不存在")
    try:
        plan = PlanningDomainService(db).confirm(ward_id, draft.id, body.expected_draft_version)
        confirmed_version = (draft.working_state or {}).get('confirmed_schedule_version', plan.version)
        db.commit()
        return {"id": plan.id, "status": "confirmed", "version": confirmed_version}
    except Exception:
        db.rollback()
        raise

@router.get("/wards/{ward_id}/plans/{plan_date}")
def get_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_guardian_or_ward), db: Session = Depends(get_db)):
    if principal.role == "ward": _ward_owned(principal, ward_id)
    else: owned_ward(db, principal.user_id, ward_id)
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    items = db.query(Task).filter_by(schedule_id=plan.id).order_by(Task.position)
    slots = {i["assignment_id"]: i for i in (plan.items or [])}
    return {"id": plan.id, "version": plan.version, "status": plan.status, "items": [{"id": x.id, "assignment_id": x.id, "title": x.title, "planned_minutes": x.planned_minutes, "status": x.status,
             "start_at": slots.get(x.id, {}).get("start_at"), "end_at": slots.get(x.id, {}).get("end_at"),
             "session": open_session_for_task(db, task_id=x.id)} for x in items]}
