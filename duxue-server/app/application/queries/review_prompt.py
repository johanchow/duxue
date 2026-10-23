"""Ground a free-form review invitation in today's tutoring and study records."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.infrastructure.persistence.models import StudySession, Task, TutoringProblem, TutoringSession


def review_invitation(db: Session, *, ward_id: str, review_date: date) -> dict:
    local_start = datetime.combine(review_date, time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
    start = local_start.astimezone(timezone.utc)
    end = (local_start + timedelta(days=1)).astimezone(timezone.utc)
    sessions = db.query(StudySession).filter(
        StudySession.ward_id == ward_id,
        StudySession.started_at >= start,
        StudySession.started_at < end,
    ).all()
    session_ids = [row.id for row in sessions]
    questions = []
    fallback_questions = []
    if session_ids:
        questions = db.query(TutoringProblem.summary).join(
            TutoringSession, TutoringProblem.tutoring_session_id == TutoringSession.id,
        ).filter(
            TutoringSession.ward_id == ward_id,
            TutoringSession.study_session_id.in_(session_ids),
            TutoringProblem.summary.is_not(None),
        ).order_by(TutoringProblem.created_at.desc()).limit(3).all()
        if not questions:
            fallback_questions = db.query(TutoringSession.question_summary).filter(
                TutoringSession.ward_id == ward_id,
                TutoringSession.study_session_id.in_(session_ids),
                TutoringSession.question_summary.is_not(None),
            ).order_by(TutoringSession.created_at.desc()).limit(1).all()
    task_ids = {row.task_id for row in sessions if row.task_id}
    tasks = {row.id: row for row in db.query(Task).filter(
        Task.ward_id == ward_id, Task.id.in_(task_ids),
    ).all()} if task_ids else {}
    overrun = []
    for session in sessions:
        task = tasks.get(session.task_id)
        if task and task.planned_minutes and session.active_seconds > task.planned_minutes * 60:
            overrun.append({"title": task.title, "planned_minutes": task.planned_minutes,
                            "active_minutes": (session.active_seconds + 59) // 60})
    overrun.sort(key=lambda row: row["active_minutes"] - row["planned_minutes"], reverse=True)
    prompts = []
    if questions or fallback_questions:
        summary = (questions or fallback_questions)[0][0][:80]
        prompts.append(f"今天问过“{summary}”。你现在觉得哪些弄懂了，哪些还有疑问？")
    if overrun:
        prompts.append(f"“{overrun[0]['title']}”用时比计划长。你觉得原因是什么，下次想怎么调整？")
    if not prompts:
        prompts.append("今天学了什么、哪里还不明白？有没有花时间特别久的地方？")
    return {"prompt": " ".join(prompts) + " 想到什么就用自己的话说出来。",
            "question_count": len(questions or fallback_questions), "overrun_count": len(overrun)}
