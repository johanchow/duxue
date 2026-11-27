"""P0-1 Ephemeral (4h TTL) Repository & ProductionStatusStore for MentorCourseware.

Zero PostgreSQL tables or student-domain writes. Uses Redis atomic Lua CAS when
REDIS_URL is configured and reachable, with a thread-safe InMemory fallback for
unit tests and local development without Redis.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any
from uuid import UUID

from app.application.ports.mentor_courseware import (
    MentorCoursewareRepository,
    ProductionStatusSnapshot,
    ProductionStatusStore,
)
from app.contexts.tutoring.domain.mentor_courseware import (
    CoursewareConflictError,
    MentorCourseware,
)

DEFAULT_TTL_SECONDS = 4 * 3600

_CAS_LUA = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return -1
end
local cur = cjson.decode(raw)
if tonumber(cur['state_revision']) ~= tonumber(ARGV[1]) then
  return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
return 1
"""


class InMemoryCoursewareRepository(MentorCoursewareRepository):
    """Thread-safe 4h-TTL repository implementing strict state_revision CAS."""

    def __init__(self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cmd_index: dict[str, tuple[float, str]] = {}

    def _evict(self, now: float) -> None:
        expired = [k for k, (exp, _) in self._items.items() if exp <= now]
        for k in expired:
            self._items.pop(k, None)
        expired_cmd = [k for k, (exp, _) in self._cmd_index.items() if exp <= now]
        for k in expired_cmd:
            self._cmd_index.pop(k, None)

    def get(self, courseware_id: UUID) -> MentorCourseware | None:
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            entry = self._items.get(str(courseware_id))
            if entry is None:
                return None
            return MentorCourseware.from_dict(entry[1])

    def get_by_create_command(self, guardian_id: UUID, command_id: str) -> MentorCourseware | None:
        now = time.monotonic()
        cmd_key = f"{guardian_id}:{command_id}"
        with self._lock:
            self._evict(now)
            idx = self._cmd_index.get(cmd_key)
            if idx is None:
                return None
            entry = self._items.get(idx[1])
            if entry is None:
                return None
            return MentorCourseware.from_dict(entry[1])

    def create(self, courseware: MentorCourseware, *, command_id: str) -> None:
        now = time.monotonic()
        exp = now + self._ttl
        cid = str(courseware.courseware_id)
        cmd_key = f"{courseware.guardian_id}:{command_id}"
        with self._lock:
            self._evict(now)
            self._items[cid] = (exp, courseware.to_dict())
            self._cmd_index[cmd_key] = (exp, cid)

    def save_cas(self, courseware: MentorCourseware, *, expected_state_revision: int) -> None:
        now = time.monotonic()
        cid = str(courseware.courseware_id)
        with self._lock:
            self._evict(now)
            entry = self._items.get(cid)
            if entry is None:
                raise CoursewareConflictError("courseware_expired", "课件已过期，请重新生成")
            current_rev = int(entry[1].get("state_revision", 0))
            if current_rev != expected_state_revision:
                raise CoursewareConflictError("revision_base_changed", "并发更新冲突，请刷新后重试")
            self._items[cid] = (now + self._ttl, courseware.to_dict())


class RedisCoursewareRepository(MentorCoursewareRepository):
    """Redis 4h-TTL repository using atomic Lua CAS on state_revision."""

    def __init__(self, redis_client: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._r = redis_client
        self._ttl = ttl_seconds
        self._cas = self._r.register_script(_CAS_LUA)

    @staticmethod
    def _key(courseware_id: UUID | str) -> str:
        return f"duxue:mentor_courseware:{courseware_id}"

    @staticmethod
    def _cmd_key(guardian_id: UUID, command_id: str) -> str:
        return f"duxue:mentor_courseware_cmd:{guardian_id}:{command_id}"

    def get(self, courseware_id: UUID) -> MentorCourseware | None:
        raw = self._r.get(self._key(courseware_id))
        if not raw:
            return None
        return MentorCourseware.from_dict(json.loads(raw))

    def get_by_create_command(self, guardian_id: UUID, command_id: str) -> MentorCourseware | None:
        cid = self._r.get(self._cmd_key(guardian_id, command_id))
        if not cid:
            return None
        if isinstance(cid, bytes):
            cid = cid.decode("utf-8")
        return self.get(UUID(cid))

    def create(self, courseware: MentorCourseware, *, command_id: str) -> None:
        payload = json.dumps(courseware.to_dict(), ensure_ascii=False)
        cid = str(courseware.courseware_id)
        pipe = self._r.pipeline()
        pipe.set(self._key(cid), payload, ex=self._ttl)
        pipe.set(self._cmd_key(courseware.guardian_id, command_id), cid, ex=self._ttl)
        pipe.execute()

    def save_cas(self, courseware: MentorCourseware, *, expected_state_revision: int) -> None:
        payload = json.dumps(courseware.to_dict(), ensure_ascii=False)
        res = int(self._cas(keys=[self._key(courseware.courseware_id)], args=[expected_state_revision, payload, self._ttl]))
        if res == -1:
            raise CoursewareConflictError("courseware_expired", "课件已过期，请重新生成")
        if res == 0:
            raise CoursewareConflictError("revision_base_changed", "并发更新冲突，请刷新后重试")


class InMemoryProductionStatusStore(ProductionStatusStore):
    def __init__(self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, ProductionStatusSnapshot]] = {}

    def set_status(self, snapshot: ProductionStatusSnapshot) -> None:
        with self._lock:
            self._data[snapshot.courseware_id] = (time.monotonic() + self._ttl, snapshot)

    def get_status(self, courseware_id: UUID) -> ProductionStatusSnapshot | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(str(courseware_id))
            if entry is None or entry[0] <= now:
                self._data.pop(str(courseware_id), None)
                return None
            return entry[1]


class RedisProductionStatusStore(ProductionStatusStore):
    def __init__(self, redis_client: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._r = redis_client
        self._ttl = ttl_seconds

    @staticmethod
    def _key(courseware_id: UUID | str) -> str:
        return f"duxue:mentor_courseware_status:{courseware_id}"

    def set_status(self, snapshot: ProductionStatusSnapshot) -> None:
        self._r.set(self._key(snapshot.courseware_id), json.dumps(snapshot.to_dict(), ensure_ascii=False), ex=self._ttl)

    def get_status(self, courseware_id: UUID) -> ProductionStatusSnapshot | None:
        raw = self._r.get(self._key(courseware_id))
        if not raw:
            return None
        data = json.loads(raw)
        return ProductionStatusSnapshot(
            courseware_id=str(data["courseware_id"]),
            stage=data["stage"],
            message=str(data.get("message") or ""),
            revision_id=data.get("revision_id"),
            updated_at=str(data.get("updated_at") or ""),
            error_code=data.get("error_code"),
        )


def build_default_courseware_stores() -> tuple[MentorCoursewareRepository, ProductionStatusStore]:
    """Use Redis when REDIS_URL is configured and reachable, else in-memory store."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        try:
            import redis  # type: ignore[import-untyped]

            client = redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
            client.ping()
            return RedisCoursewareRepository(client), RedisProductionStatusStore(client)
        except Exception:
            pass
    return InMemoryCoursewareRepository(), InMemoryProductionStatusStore()
