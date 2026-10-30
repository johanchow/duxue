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
CATEGORIES = (
    "scene_routing", "real_regression", "answer_protection", "pronunciation_context",
    "visual", "fact_vs_reasoning", "teaching_quality", "safety", "multi_turn",
)
SINGLE_TURN_CATEGORIES = CATEGORIES[:-1]
CATEGORY_TAGS = {
    "answer_protection": "answer-protection", "pronunciation_context": "pronounce",
    "visual": "visual", "fact_vs_reasoning": "depth", "teaching_quality": "rubric",
    "safety": "safety",
}
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
    out += (
        expect.lesson_source_contains_any + expect.lesson_source_contains_all
        + expect.content_contains_any + expect.content_not_contains
    )
    return out


def pii_findings(case: EvalCase) -> list[str]:
    found = []
    for text in _strings(case):
        for kind, pattern in _DETECTORS.items():
            if pattern.search(text):
                found.append(kind)
    return sorted(set(found))


def read_object(path: Path) -> dict:
    """One case file is one pretty-printed JSON object."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path.name}: empty file")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name}: invalid JSON ({error})") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected one JSON object")
    return data


def _case_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        file for file in path.rglob("*.json")
        if "multi_turn" not in file.relative_to(path).parts
    )


def load_cases(path: Path | None = None) -> list[EvalCase]:
    """Single-turn cases from one file or a category tree, in filename order."""
    path = path if path is not None else DATA_DIR
    cases: list[EvalCase] = []
    for file in _case_files(path):
        try:
            record = read_object(file)
            cases.append(EvalCase.model_validate(record))
        except (ValueError, ValidationError) as error:
            raise ValueError(f"{file.name}: {error}") from error
    return cases


def validate_layout(path: Path = DATA_DIR) -> list[str]:
    """One directory per category; each case is its own JSON file named after its id."""
    problems: list[str] = []
    for category in CATEGORIES:
        folder = path / category
        if not folder.is_dir():
            problems.append(f"missing category folder: {category}")
            continue
        if not list(folder.glob("*.json")):
            problems.append(f"empty category: {category}")
    for file in list(path.rglob("*.json")) + list(path.rglob("*.jsonl")):
        if file.parent == path or file.parent.parent != path or file.parent.name not in CATEGORIES:
            problems.append(f"unexpected dataset file: {file.relative_to(path)}")
            continue
        category = file.parent.name
        try:
            record = read_object(file)
        except ValueError as error:
            problems.append(str(error))
            continue
        if record.get("id") != file.stem:
            problems.append(f"{file.relative_to(path)}: filename must match id")
        if category == "multi_turn":
            continue
        try:
            case = load_cases(file)[0]
        except (ValueError, IndexError) as error:
            problems.append(str(error))
            continue
        if category == "scene_routing" and case.component != "companion.intent":
            problems.append(f"{case.id}: scene_routing requires companion.intent")
        elif category == "real_regression" and (case.component != "tutoring.turn" or case.source != "real"):
            problems.append(f"{case.id}: real_regression requires a real tutoring turn")
        elif category in CATEGORY_TAGS and CATEGORY_TAGS[category] not in case.tags:
            problems.append(f"{case.id}: missing category tag {CATEGORY_TAGS[category]}")
    return problems


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
