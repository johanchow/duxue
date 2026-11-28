from app.contexts.artifact_workspace.domain.versions import TEMPORARY_LIFETIME
from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    MentorCourseware,
)
from app.infrastructure.persistence.artifact_tables import artifacts as root
from app.infrastructure.persistence.artifact_tables import receipts, versions
from app.infrastructure.persistence.database import engine


def live(now):
    return or_(root.c.retention_status == "saved", root.c.expires_at > now)


class PgCoursewareRepository:
    def __init__(self, db=engine, legacy=None):
        self.legacy = legacy
        self.db = db

    def _read(self, predicate):
        # Hold a shared root lock so snapshots and receipts belong to the
        # exact revision returned to the caller under READ COMMITTED.
        stmt = select(
            root.c.artifact_id,
            root.c.payload,
            root.c.branch,
            root.c.cursor,
            root.c.state_revision,
            root.c.updated_at,
            root.c.expires_at,
        ).where(
            root.c.artifact_type == "interactive_courseware",
            predicate,
            live(datetime.now(timezone.utc)),
        )
        with self.db.begin() as conn:
            row = conn.execute(stmt.with_for_update(read=True)).one_or_none()
            if row is None:
                return None
            snapshots = dict(
                conn.execute(
                    select(versions.c.version_no, versions.c.payload).where(
                        versions.c.artifact_id == row.artifact_id,
                        versions.c.version_no.in_(row.branch),
                    )
                ).all()
            )
            commands = dict(row.payload.get("processed_command_ids", {}))
            commands.update(
                conn.execute(
                    select(receipts.c.command_id, receipts.c.result).where(
                        receipts.c.artifact_id == row.artifact_id
                    )
                ).all()
            )
        courseware = MentorCourseware.from_dict(
            dict(
                row.payload,
                cursor=row.cursor,
                state_revision=row.state_revision,
                versions=[snapshots[number] for number in row.branch],
                processed_command_ids=commands,
            )
        )
        courseware.updated_at = row.updated_at.isoformat()
        courseware.expires_at = row.expires_at.isoformat() if row.expires_at else None
        return courseware

    def get(self, courseware_id):
        return self._read(root.c.artifact_id == courseware_id) or (
            self.legacy.get(courseware_id) if self.legacy else None
        )

    def get_by_create_command(self, guardian_id, command_id):
        return self._read(
            and_(root.c.owner_id == guardian_id, root.c.command_id == command_id)
        )

    def create(self, courseware, *, command_id):
        now = datetime.now(timezone.utc)
        try:
            with self.db.begin() as conn:
                conn.execute(
                    insert(root).values(
                        artifact_id=courseware.courseware_id,
                        artifact_type="interactive_courseware",
                        owner_id=courseware.guardian_id,
                        command_id=command_id,
                        title="",
                        photos=[],
                        branch=[],
                        cursor=-1,
                        retention_status="temporary",
                        state_revision=courseware.state_revision,
                        payload=courseware.to_dict(),
                        updated_at=now,
                        expires_at=now + TEMPORARY_LIFETIME,
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
        commands = payload.pop("processed_command_ids")
        baseline = courseware.current_baseline
        payload["question_text"] = (
            baseline.stem_text if baseline else ""
        ) or courseware.prompt_text
        cid = courseware.courseware_id
        predicate = and_(
            root.c.artifact_type == "interactive_courseware",
            root.c.artifact_id == cid,
            root.c.state_revision == expected_state_revision,
            live(now),
        )
        with self.db.begin() as conn:
            if courseware.retention_status == "deleted":
                res = conn.execute(delete(root).where(predicate))
            else:
                values = dict(
                    payload=payload,
                    branch=[v["version_no"] for v in chain],
                    cursor=courseware.cursor,
                    title=courseware.title,
                    retention_status=courseware.retention_status,
                    state_revision=courseware.state_revision,
                    updated_at=now,
                    expires_at=now + TEMPORARY_LIFETIME
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
            recorded = set(
                conn.execute(
                    select(receipts.c.command_id).where(receipts.c.artifact_id == cid)
                ).scalars()
            )
            for command_id, result in commands.items():
                if command_id not in recorded:
                    digest = sha256(
                        json.dumps(result, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest()
                    conn.execute(
                        insert(receipts).values(
                            artifact_id=cid,
                            command_id=command_id,
                            digest=digest,
                            result=result,
                        )
                    )
            scope = versions.c.artifact_id == cid
            existing = set(
                conn.execute(select(versions.c.version_no).where(scope)).scalars()
            )
            for v in chain:
                if v["version_no"] not in existing:
                    conn.execute(
                        insert(versions).values(
                            artifact_id=cid, version_no=v["version_no"], payload=v
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
            root.c.artifact_id.label("courseware_id"),
            root.c.title,
            func.coalesce(
                root.c.payload["question_text"].as_string(),
                root.c.payload["prompt_text"].as_string(),
            ).label("question_text"),
            root.c.updated_at,
            root.c.state_revision,
            root.c.payload["thumbnail"].as_string().label("thumbnail"),
            root.c.payload["subject"].as_string().label("subject"),
        ).where(
            root.c.artifact_type == "interactive_courseware",
            root.c.owner_id == guardian_id,
            root.c.retention_status == "saved",
        )
        if before:
            date, cid = before
            stmt = stmt.where(
                or_(
                    root.c.updated_at < date,
                    and_(root.c.updated_at == date, root.c.artifact_id < cid),
                )
            )
        with self.db.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    stmt.order_by(
                        root.c.updated_at.desc(), root.c.artifact_id.desc()
                    ).limit(limit)
                ).mappings()
            ]

    def saved_photos(self, guardian_id, cid):
        with self.db.connect() as conn:
            return (
                conn.scalar(
                    select(root.c.photos).where(
                        root.c.artifact_id == cid,
                        root.c.owner_id == guardian_id,
                        root.c.retention_status == "saved",
                    )
                )
                or []
            )
