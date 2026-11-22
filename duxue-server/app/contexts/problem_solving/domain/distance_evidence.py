"""Distance labels read from a single line, with provenance from authorized crops."""

from collections import deque
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

Symbol = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$")]
DistanceKind = Literal["adjacent_spacing", "midpoint_velocity"]


def part_key(part: str) -> str:
    label = part.strip().replace("（", "(").replace("）", ")")
    if label.endswith(")"):
        question, sep, subpart = label[:-1].rpartition("(")
        if sep and subpart.strip().isdecimal() and (not question.strip() or question.strip().isdecimal()):
            return subpart.strip()
    return label


class DistanceLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: Symbol
    start: Symbol
    end: Symbol


class DistanceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    part: str = Field(min_length=1, max_length=32)
    kind: DistanceKind
    start: Symbol
    middle: Symbol
    end: Symbol
    interval_symbol: Symbol | None = None

    @model_validator(mode="before")
    @classmethod
    def discard_unused_interval(cls, raw):
        if isinstance(raw, dict) and raw.get("kind") == "adjacent_spacing":
            return {key: value for key, value in raw.items() if key != "interval_symbol"}
        return raw

    @model_validator(mode="after")
    def require_velocity_interval(self):
        if self.kind == "midpoint_velocity" and self.interval_symbol is None:
            raise ValueError("midpoint_velocity requires the time interval symbol")
        return self


class DistanceFigure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    crop_ref: str = Field(min_length=1, max_length=64)
    labels: tuple[DistanceLabel, ...] = Field(min_length=1, max_length=8)
    questions: tuple[DistanceQuestion, ...] = Field(min_length=1, max_length=6)

    def distance(self, start: str, end: str) -> str | None:
        """Sum oriented lengths along the shortest path between the two points."""
        edges: dict[str, list[tuple[str, str, int]]] = {}
        for label in self.labels:
            edges.setdefault(label.start, []).append((label.end, label.symbol, 1))
            edges.setdefault(label.end, []).append((label.start, label.symbol, -1))
        queue = deque([(start, ())])
        visited = {start}
        while queue:
            point, path = queue.popleft()
            if point == end:
                positive = [symbol for symbol, sign in path if sign > 0]
                negative = [symbol for symbol, sign in path if sign < 0]
                return "+".join(positive) + "".join("-" + symbol for symbol in negative)
            for next_point, symbol, sign in edges.get(point, []):
                if next_point not in visited:
                    visited.add(next_point)
                    queue.append((next_point, (*path, (symbol, sign))))
        return None

    def formulas(self) -> list[dict]:
        if len({label.symbol for label in self.labels}) != len(self.labels):
            return []
        forms = []
        for question in self.questions:
            a, b, c = question.start, question.middle, question.end
            if len({a, b, c}) != 3:
                return []
            if question.kind == "adjacent_spacing":
                first, second = self.distance(a, b), self.distance(b, c)
                if not first or not second:
                    return []
                forms.append({
                    "part": question.part,
                    "expected": {"first_interval": first, "second_interval": second},
                    "latex": rf"{a}{b}={first},\quad {b}{c}={second}",
                })
            else:
                full = self.distance(a, c)
                if not full:
                    return []
                interval = question.interval_symbol
                forms.append({
                    "part": question.part,
                    "interval_symbol": interval,
                    "expected": {"velocity": f"({full})/(2*{interval})"},
                    "latex": rf"v_{{{b}}}=\dfrac{{{a}{c}}}{{2{interval}}}=\dfrac{{{full}}}{{2{interval}}}",
                })
        return forms


class DistanceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["not_needed", "unclear", "read"]
    figures: tuple[DistanceFigure, ...] = Field(default=(), max_length=4)

    def formulas(self) -> list[dict]:
        forms = [row for figure in self.figures for row in figure.formulas()]
        return [
            {**row, "slot": f"[[distance_{i}]]"}
            for i, row in enumerate(forms, start=1)
        ]


def read_distance_evidence(raw, crops: list[dict]) -> dict | None:
    """Accept endpoint readings only when their named crop was actually shown."""
    by_ref = {crop["crop_ref"]: crop for crop in crops}
    sources = {
        ref: {key: crop[key] for key in ("crop_ref", "image_ref", "bbox")}
        for ref, crop in by_ref.items()
    }
    try:
        evidence = DistanceEvidence.model_validate(raw)
    except ValidationError as error:
        return {
            "status": "unclear", "reason": "invalid_distance_read", "sources": list(sources.values()),
            "format_errors": [
                {"field": row["loc"], "type": row["type"], "message": row["msg"]}
                for row in error.errors(include_url=False, include_context=False, include_input=False)[:6]
            ],
        }
    if evidence.status == "not_needed" and not evidence.figures:
        return None
    if (
        evidence.status != "read"
        or not evidence.figures
        or any(f.crop_ref not in by_ref or not f.formulas() for f in evidence.figures)
    ):
        return {"status": "unclear", "reason": "unconfirmed_distance_read", "sources": list(sources.values())}
    return {
        "status": "read",
        "figures": [f.model_dump(mode="json", exclude_none=True) for f in evidence.figures],
        "sources": [
            sources[ref]
            for ref in dict.fromkeys(f.crop_ref for f in evidence.figures)
        ],
        "formulas": evidence.formulas(),
    }


def endpoint_readings(evidence: dict) -> dict[tuple, tuple]:
    """Compare the same subproblem across reads without comparing crop identities."""
    images = {source["crop_ref"]: source["image_ref"] for source in evidence["sources"]}
    return {
        (part_key(question["part"]), question["kind"]): (
            images[figure["crop_ref"]],
            tuple(sorted((label["symbol"].replace("_", ""), label["start"], label["end"])
                         for label in figure["labels"])),
        )
        for figure in evidence["figures"]
        for question in figure["questions"]
    }
