"""Load, scrub and validate the dataset. Validation is what CI runs; there is no network here."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import ValidationError

from evals.schema import ASSET_NAME, MAX_WINDOW, EvalCase

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
ASSETS_DIR = ROOT / "var" / "eval-assets"
RESULTS_DIR = ROOT / "var" / "evals"

_PHONE = re.compile(r"(?<!\d)1\d{10}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_CN_ID = re.compile(r"(?<![\dXx])\d{17}[\dXx](?![\dXx])")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_LONG_NUMBER = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_DETECTORS = {
    "phone": _PHONE, "email": _EMAIL, "cn_id": _CN_ID, "uuid": _UUID, "long_number": _LONG_NUMBER,
    "data_url": re.compile(r"data:[\w/+.-]+;base64", re.I),
    "storage_path": re.compile(r"\bward/[0-9a-f-]{8,}/", re.I),
    "url": re.compile(r"https?://", re.I),
}


def scrub(text: str, names: tuple[str, ...] = ()) -> str:
    """Replace identifiers before a real utterance can enter the dataset."""
    for name in names:
        if name:
            text = text.replace(name, "[name]")
    text = _EMAIL.sub("[email]", text)
    text = _UUID.sub("[id]", text)
    text = _CN_ID.sub("[id]", text)
    text = _PHONE.sub("[phone]", text)
    return _LONG_NUMBER.sub("[number]", text)


def _strings(case: EvalCase) -> list[str]:
    out = [case.student_said, case.note or "", case.conversation_id]
    out += [row.text for row in case.history]
    out += [case.context.task_title or ""]
    if case.context.problem:
        out += [case.context.problem.summary or "", case.context.problem.evidence_summary or ""]
    expect = case.expect
    out += expect.lesson_source_contains_any + expect.content_contains_any + expect.content_not_contains
    return out


def pii_findings(case: EvalCase) -> list[str]:
    found = []
    for text in _strings(case):
        for kind, pattern in _DETECTORS.items():
            if pattern.search(text):
                found.append(kind)
    return sorted(set(found))


def parse_line(line: str, where: str) -> EvalCase:
    try:
        return EvalCase.model_validate(json.loads(line))
    except (ValueError, ValidationError) as error:
        raise ValueError(f"{where}: {error}") from error


def load_cases(path: Path | None = None) -> list[EvalCase]:
    """All ``*.jsonl`` under ``path`` (default ``evals/data``), in file order."""
    path = path or DATA_DIR
    files = [path] if path.is_file() else sorted(path.glob("*.jsonl"))
    cases: list[EvalCase] = []
    for file in files:
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                cases.append(parse_line(line, f"{file.name}:{number}"))
    return cases


def dataset_hash(cases: list[EvalCase]) -> str:
    """Stable id of the dataset content. Results are comparable only when this matches."""
    payload = [case.model_dump(mode="json") for case in sorted(cases, key=lambda c: c.id)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def validate(cases: list[EvalCase]) -> list[str]:
    """Human-readable problems. Empty means the dataset may be committed and run."""
    problems: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            problems.append(f"{case.id}: duplicate id")
        seen.add(case.id)
        if case.label_status == "confirmed":
            if not case.reviewed_by:
                problems.append(f"{case.id}: confirmed needs reviewed_by")
            if not case.expect.is_specific():
                problems.append(f"{case.id}: confirmed needs an expectation beyond 'no fallback'")
        elif case.reviewed_by:
            problems.append(f"{case.id}: reviewed_by is set but label_status is {case.label_status}")
        if len(case.history) > MAX_WINDOW:
            problems.append(f"{case.id}: history longer than the production window ({MAX_WINDOW})")
        if len(case.asset_names) > MAX_WINDOW:
            problems.append(f"{case.id}: more images than the production window keeps ({MAX_WINDOW})")
        for name in case.asset_names:
            if not ASSET_NAME.match(name):
                problems.append(f"{case.id}: bad asset name {name!r}")
        findings = pii_findings(case)
        if findings:
            problems.append(f"{case.id}: contains {', '.join(findings)}")
        if case.source == "real" and not case.conversation_id.strip():
            problems.append(f"{case.id}: real case needs conversation_id")
    return problems
