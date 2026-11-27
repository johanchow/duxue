from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    MentorCourseware,
)
from app.infrastructure.persistence.courseware_tables import coursewares as root
from app.infrastructure.persistence.courseware_tables import versions
from app.infrastructure.persistence.database import engine


def live(now):
    return or_(root.c.retention_status == "saved", root.c.expires_at > now)


class PgCoursewareRepository:
    def __init__(self, db=engine, legacy=None):
        self.legacy = legacy
        self.db = db

    def _read(self, predicate):
        # A single statement gives the root and version chain one consistent snapshot.
        stmt = (
            select(
                root.c.payload,
                root.c.updated_at,
                root.c.expires_at,
                versions.c.payload.label("version"),
            )
            .select_from(root.outerjoin(versions))
            .where(predicate, live(datetime.now(timezone.utc)))
            .order_by(versions.c.version_no)
        )
        with self.db.connect() as conn:
            rows = conn.execute(stmt).all()
        if rows:
            cw = MentorCourseware.from_dict(
                dict(rows[0].payload, versions=[r.version for r in rows if r.version])
            )
            cw.updated_at = rows[0].updated_at.isoformat()
            cw.expires_at = (
                rows[0].expires_at.isoformat() if rows[0].expires_at else None
            )
            return cw

    def get(self, courseware_id):
        return self._read(root.c.courseware_id == courseware_id) or (
            self.legacy.get(courseware_id) if self.legacy else None
        )

    def get_by_create_command(self, guardian_id, command_id):
        return self._read(
            and_(root.c.guardian_id == guardian_id, root.c.command_id == command_id)
        )

    def create(self, courseware, *, command_id):
        now = datetime.now(timezone.utc)
        try:
            with self.db.begin() as conn:
                conn.execute(delete(root).where(root.c.expires_at <= now))
                conn.execute(
                    insert(root).values(
                        courseware_id=courseware.courseware_id,
                        guardian_id=courseware.guardian_id,
                        command_id=command_id,
                        title="",
                        photos=[],
                        retention_status="temporary",
                        state_revision=courseware.state_revision,
                        payload=courseware.to_dict(),
                        updated_at=now,
                        expires_at=now + timedelta(hours=4),
                    )
                )
        except IntegrityError:
            winner = self.get_by_create_command(courseware.guardian_id, command_id)
            if winner is None:
                raise
            if (
                winner.prompt_text != courseware.prompt_text
                or winner.attachment_keys != courseware.attachment_keys
            ):
                raise CoursewareConflictError(
                    "idempotency_payload_mismatch", "重复请求的题目不同"
                ) from None
            return winner

    def save_cas(self, courseware, *, expected_state_revision, photos=None):
        now = datetime.now(timezone.utc)
        payload = courseware.to_dict()
        chain = payload.pop("versions")
        baseline = courseware.current_baseline
        payload["question_text"] = (baseline.stem_text if baseline else "") or courseware.prompt_text
        cid = courseware.courseware_id
        predicate = and_(
            root.c.courseware_id == cid,
            root.c.state_revision == expected_state_revision,
            live(now),
        )
        with self.db.begin() as conn:
            if courseware.retention_status == "deleted":
                res = conn.execute(delete(root).where(predicate))
            else:
                values = dict(
                    payload=payload,
                    title=courseware.title,
                    retention_status=courseware.retention_status,
                    state_revision=courseware.state_revision,
                    updated_at=now,
                    expires_at=now + timedelta(hours=4)
                    if courseware.retention_status == "temporary"
                    else None,
                )
                if photos is not None:
                    values["photos"] = photos
                res = conn.execute(update(root).where(predicate).values(**values))
            if res.rowcount != 1:
                if self.legacy and self.legacy.get(cid):
                    if courseware.retention_status != "temporary":
                        raise CoursewareConflictError(
                            "legacy_courseware", "请重新生成此旧课件后保存"
                        )
                    self.legacy.save_cas(
                        courseware, expected_state_revision=expected_state_revision
                    )
                    return
                raise CoursewareConflictError(
                    "revision_base_changed", "课件已过期或已更新"
                )
            if courseware.retention_status == "deleted":
                return
            scope = versions.c.courseware_id == cid
            existing = set(
                conn.execute(select(versions.c.version_no).where(scope)).scalars()
            )
            keep = {v["version_no"] for v in chain}
            if existing - keep:
                conn.execute(
                    delete(versions).where(
                        scope, versions.c.version_no.in_(existing - keep)
                    )
                )
            for v in chain:
                if v["version_no"] not in existing:
                    conn.execute(
                        insert(versions).values(
                            courseware_id=cid, version_no=v["version_no"], payload=v
                        )
                    )

    def expire_temporary(self):
        with self.db.begin() as conn:
            return conn.execute(
                delete(root).where(
                    root.c.retention_status == "temporary",
                    root.c.expires_at <= datetime.now(timezone.utc),
                )
            ).rowcount

    def list_saved(self, guardian_id, before=None, limit=30):
        stmt = select(
            root.c.courseware_id,
            root.c.title,
            func.coalesce(root.c.payload["question_text"].as_string(), root.c.payload["prompt_text"].as_string()).label("question_text"),
            root.c.updated_at,
            root.c.state_revision,
            root.c.payload["thumbnail"].as_string().label("thumbnail"),
            root.c.payload["subject"].as_string().label("subject"),
        ).where(root.c.guardian_id == guardian_id, root.c.retention_status == "saved")
        if before:
            date, cid = before
            stmt = stmt.where(
                or_(
                    root.c.updated_at < date,
                    and_(root.c.updated_at == date, root.c.courseware_id < cid),
                )
            )
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    stmt.order_by(
                        root.c.updated_at.desc(), root.c.courseware_id.desc()
                    ).limit(limit)
                ).mappings()
            ]

    def saved_photos(self, guardian_id, cid):
        with self.db.connect() as conn:
            return (
                conn.scalar(
                    select(root.c.photos).where(
                        root.c.courseware_id == cid,
                        root.c.guardian_id == guardian_id,
                        root.c.retention_status == "saved",
                    )
                )
                or []
            )
