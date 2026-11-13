"""Visible evidence and time accounting. No model calls or semantic heuristics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

ACTIVITIES = frozenset(
    {
        "writing",
        "reading_material",
        "handling_material",
        "still_with_material",
        "other_visible_activity",
        "away",
        "unknown",
    }
)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value


@dataclass(frozen=True)
class EvidenceFrame:
    id: str
    at: datetime


@dataclass(frozen=True)
class Manifest:
    ward_id: str
    camera_id: str
    assignment_revision: int
    start: datetime
    end: datetime
    frames: tuple[EvidenceFrame, ...]

    def __post_init__(self):
        if not 0 < (aware(self.end) - aware(self.start)).total_seconds() <= 60:
            raise ValueError("invalid target window")
        if len({f.id for f in self.frames}) != len(self.frames):
            raise ValueError("duplicate evidence")
        for frame in self.frames:
            aware(frame.at)


@dataclass(frozen=True)
class Cell:
    start: datetime
    end: datetime
    activity: str
    evidence: tuple[str, ...]
    uncertainty_reason: str | None = None

    def __post_init__(self):
        if aware(self.start) >= aware(self.end):
            raise ValueError("invalid interval")
        if self.activity not in ACTIVITIES | {"missing"}:
            raise ValueError("invalid activity")
        if self.activity != "missing" and not self.evidence:
            raise ValueError("evidence required")

    @property
    def seconds(self):
        return (self.end - self.start).total_seconds()


def validate_outcome(manifest: Manifest, rows: list[dict]) -> list[Cell]:
    """One output cell per received 15-second slot; context cannot fill holes."""
    slots: dict[datetime, set[str]] = defaultdict(set)
    for frame in manifest.frames:
        if manifest.start <= frame.at < manifest.end:
            offset = int((frame.at - manifest.start).total_seconds() // 15) * 15
            slots[manifest.start + timedelta(seconds=offset)].add(frame.id)
    accepted = {}
    for row in rows:
        start, end = (aware(datetime.fromisoformat(row[k])) for k in ("start", "end"))
        refs = tuple(row["evidence_frame_ids"])
        if (
            start not in slots
            or start in accepted
            or end != min(start + timedelta(seconds=15), manifest.end)
            or not refs
            or not set(refs) <= slots[start]
            or row["activity"] not in ACTIVITIES
        ):
            raise ValueError("invalid slot, evidence, or activity")
        accepted[start] = Cell(
            start, end, row["activity"], refs, row.get("uncertainty_reason")
        )
    # A readable frame omitted by the model is unknown, never missing or away.
    for start, refs in slots.items():
        if start not in accepted:
            accepted[start] = Cell(
                start,
                min(start + timedelta(seconds=15), manifest.end),
                "unknown",
                tuple(sorted(refs)),
                "model_omitted_slot",
            )
    return sorted(accepted.values(), key=lambda c: c.start)


@dataclass
class ObservationWindow:
    fingerprint: str
    input_version: int = 1
    status: str = "pending"
    attempt_token: str | None = None

    def invalidate(self, fingerprint: str):
        if fingerprint != self.fingerprint:
            self.fingerprint = fingerprint
            self.input_version += 1
            self.status, self.attempt_token = "pending", None

    def claim(self) -> str:
        self.status, self.attempt_token = "running", str(uuid4())
        return self.attempt_token

    def accept(self, token: str, fingerprint: str):
        if (
            self.status != "running"
            or token != self.attempt_token
            or fingerprint != self.fingerprint
        ):
            raise ValueError("stale analysis attempt")
        self.status = "interpreted"
        self.attempt_token = None


class ObservationAssembler:
    def assemble(
        self, cells: list[Cell], ranges: list[tuple[datetime, datetime]] | None
    ):
        ordered = sorted(cells, key=lambda c: c.start)
        if any(a.end > b.start for a, b in zip(ordered, ordered[1:])):
            raise ValueError("select one authorized source before assembly")
        known_ranges = sorted(ranges) if ranges is not None else None
        if known_ranges is not None:
            for start, end in known_ranges:
                if aware(start) >= aware(end):
                    raise ValueError("invalid observation range")
            if any(a[1] > b[0] for a, b in zip(known_ranges, known_ranges[1:])):
                raise ValueError("overlapping observation ranges")
            clipped = []
            for start, end in known_ranges:
                cursor = start
                for cell in ordered:
                    left, right = max(start, cell.start), min(end, cell.end)
                    if left >= right:
                        continue
                    if cursor < left:
                        clipped.append(Cell(cursor, left, "missing", ()))
                    clipped.append(
                        Cell(
                            left,
                            right,
                            cell.activity,
                            cell.evidence,
                            cell.uncertainty_reason,
                        )
                    )
                    cursor = right
                if cursor < end:
                    clipped.append(Cell(cursor, end, "missing", ()))
            ordered = clipped
        totals: dict[str, float] = defaultdict(float)
        runs = []
        for cell in ordered:
            totals[cell.activity] += cell.seconds
            if (
                runs
                and runs[-1]["end"] == cell.start
                and runs[-1]["activity"] == cell.activity
            ):
                runs[-1]["end"] = cell.end
                runs[-1]["seconds"] += cell.seconds
                runs[-1]["evidence"] = sorted(
                    set(runs[-1]["evidence"]) | set(cell.evidence)
                )
            else:
                runs.append(
                    {
                        "start": cell.start,
                        "end": cell.end,
                        "activity": cell.activity,
                        "seconds": cell.seconds,
                        "evidence": list(cell.evidence),
                    }
                )
        received = sum(v for k, v in totals.items() if k != "missing")
        interpretable = received - totals.get("unknown", 0)
        expected = (
            sum((b - a).total_seconds() for a, b in known_ranges)
            if known_ranges is not None
            else None
        )
        episodes = []
        episode = None
        learning = {
            "writing",
            "reading_material",
            "handling_material",
            "still_with_material",
        }
        for run in runs:
            breaks = (run["activity"] == "away" and run["seconds"] >= 300) or (
                run["activity"] in {"unknown", "missing"} and run["seconds"] >= 120
            )
            if episode and (breaks or run["start"] > episode["end"]):
                episodes.append(episode)
                episode = None
            if run["activity"] in learning:
                if episode is None:
                    episode = {
                        "start": run["start"],
                        "end": run["end"],
                        "activity_totals": {},
                        "source_refs": [],
                    }
                episode["end"] = run["end"]
            elif episode and not breaks:
                episode["end"] = run["end"]
            if episode:
                totals_in_episode = episode["activity_totals"]
                totals_in_episode[run["activity"]] = (
                    totals_in_episode.get(run["activity"], 0) + run["seconds"]
                )
                episode["source_refs"] = sorted(
                    set(episode["source_refs"]) | set(run["evidence"])
                )
        if episode:
            episodes.append(episode)
        return {
            "totals": dict(totals),
            "runs": runs,
            "episodes": episodes,
            "coverage": {
                "expected_seconds": expected,
                "received_seconds": received,
                "interpretable_seconds": interpretable,
                "unknown_seconds": totals.get("unknown", 0),
                "missing_seconds": totals.get("missing", 0)
                if expected is not None
                else None,
                "ratio": received / expected if expected else None,
            },
        }
