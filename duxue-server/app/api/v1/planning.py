from .common import *
from .common import _ward_owned, open_session_for_task

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


def _plan_intake_attachments(ward_id: str, keys: list[str]) -> None:
    prefix = f"ward/{ward_id}/plan-intake/"
    if any(not key.startswith(prefix) or not storage.exists(key) for key in keys):
        raise HTTPException(400, "invalid plan intake attachment")


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


@router.post("/wards/{ward_id}/plan-intake/upload-url")
def plan_intake_upload_url(ward_id: str, body: UploadUrlRequest, request: Request, principal: Principal = Depends(current_ward)):
    _ward_owned(principal, ward_id)
    extension = body.extension.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(400, "unsupported image extension")
    if not body.content_type.startswith("image/"):
        raise HTTPException(400, "unsupported image content type")
    key = f"ward/{ward_id}/plan-intake/{secrets.token_hex(16)}.{extension}"
    base_url = str(request.base_url) if settings.storage_backend == "local" else settings.public_base_url
    url, expires, headers = storage.upload_url(key, base_url, body.content_type)
    return {"upload_url": url, "oss_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc), "headers": headers}


@router.post("/wards/{ward_id}/plans/{plan_date}/intake")
def respond_to_plan_intake(ward_id: str, plan_date: date, body: PlanIntakeRequest, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    # The API stores schedule dates against the server's UTC clock; using the
    # host-local date here made the same UTC request fail around midnight.
    if plan_date != now().date():
        raise HTTPException(400, "plan intake is only available for today")
    _plan_intake_attachments(ward_id, body.attachment_keys)
    ward = db.get(Ward, ward_id)
    tasks = db.query(Task).filter_by(ward_id=ward_id).filter(Task.status != "completed").all()
    try:
        return PlanIntakeService().respond(
            ward={"id": ward.id, "display_name": ward.display_name, "grade_stage": ward.grade_stage},
            tasks=[{"id": task.id, "title": task.title, "details": task.details} for task in tasks],
            request=body,
        ).model_dump(mode="json")
    except TaskIntakeError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/wards/{ward_id}/plans/{plan_date}/intake/confirm", status_code=201)
def confirm_plan_intake(ward_id: str, plan_date: date, body: PlanIntakeConfirm, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if plan_date != now().date():
        raise HTTPException(400, "plan intake is only available for today")
    _plan_intake_attachments(ward_id, body.attachment_keys)
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is not None:
        existing = db.query(Task).filter_by(schedule_id=plan.id).all()
        if any(item.status != "pending" for item in existing):
            raise HTTPException(409, "a started or completed plan cannot be changed")
    try:
        if any(item.new_task == (item.assignment_id is not None) for item in body.items):
            raise HTTPException(400, "plan task source is invalid")
        assignment_ids = {item.assignment_id for item in body.items if item.assignment_id}
        owned = db.query(Task).filter(Task.id.in_(assignment_ids)).filter_by(ward_id=ward_id).all() if assignment_ids else []
        if {row.id for row in owned} != assignment_ids:
            raise HTTPException(400, "plan contains a task that does not belong to this ward")
        if plan is None:
            plan = DailySchedule(ward_id=ward_id, schedule_date=plan_date)
            db.add(plan)
            db.flush()
        else:
            db.query(Task).filter_by(schedule_id=plan.id).update({Task.schedule_id: None, Task.position: None, Task.planned_minutes: None})
        for position, item in enumerate(body.items):
            assignment_id = item.assignment_id
            if item.new_task:
                created = Task(ward_id=ward_id, title=item.title, details=item.details, source="ward")
                db.add(created)
                db.flush()
                assignment_id = created.id
            task = db.get(Task, assignment_id)
            task.schedule_id, task.position, task.planned_minutes = plan.id, position, item.planned_minutes
        plan.status = "confirmed"
        plan.confirmed_at = now()
        db.commit()
    except Exception:
        db.rollback()
        raise
    for key in body.attachment_keys:
        storage.delete(key)
    return {"id": plan.id, "status": plan.status}


@router.post("/wards/{ward_id}/plan-intake/cleanup", status_code=204)
def cleanup_plan_intake(ward_id: str, body: PlanIntakeCleanup, principal: Principal = Depends(current_ward)):
    _ward_owned(principal, ward_id)
    _plan_intake_attachments(ward_id, body.attachment_keys)
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
    rows = db.query(Task).filter_by(ward_id=ward_id).filter(Task.status != "completed").all()
    return [{"id": x.id, "title": x.title, "details": x.details, "due_date": x.due_date, "status": x.status,
             "session": open_session_for_task(db, task_id=x.id)} for x in rows]

@router.put("/wards/{ward_id}/plans/{plan_date}")
def save_plan(ward_id: str, plan_date: date, body: PlanDraft, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id)
    if body.plan_date != plan_date: raise HTTPException(400, "date mismatch")
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: plan = DailySchedule(ward_id=ward_id, schedule_date=plan_date); db.add(plan); db.flush()
    if plan.status == "confirmed": raise HTTPException(409, "confirmed plan cannot be changed")
    db.query(Task).filter_by(schedule_id=plan.id).update({Task.schedule_id: None, Task.position: None, Task.planned_minutes: None})
    for position, item in enumerate(body.items):
        task = db.get(Task, item.get("assignment_id")) if item.get("assignment_id") else None
        if task is None:
            task = Task(ward_id=ward_id, title=item.get("title", "学习任务"), source="ward")
            db.add(task); db.flush()
        task.schedule_id, task.position, task.planned_minutes = plan.id, position, int(item.get("planned_minutes", 30))
    db.commit(); return {"id": plan.id, "status": plan.status}

@router.post("/wards/{ward_id}/plans/{plan_date}/confirm")
def confirm_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_ward), db: Session = Depends(get_db)):
    _ward_owned(principal, ward_id); plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    plan.status = "confirmed"; plan.confirmed_at = now(); db.commit(); return {"id": plan.id, "status": plan.status}

@router.get("/wards/{ward_id}/plans/{plan_date}")
def get_plan(ward_id: str, plan_date: date, principal: Principal = Depends(current_guardian_or_ward), db: Session = Depends(get_db)):
    if principal.role == "ward": _ward_owned(principal, ward_id)
    else: owned_ward(db, principal.user_id, ward_id)
    plan = db.query(DailySchedule).filter_by(ward_id=ward_id, schedule_date=plan_date).one_or_none()
    if plan is None: raise HTTPException(404, "plan not found")
    items = db.query(Task).filter_by(schedule_id=plan.id).order_by(Task.position)
    return {"id": plan.id, "status": plan.status, "items": [{"id": x.id, "assignment_id": x.id, "title": x.title, "planned_minutes": x.planned_minutes, "status": x.status,
             "session": open_session_for_task(db, task_id=x.id)} for x in items]}
