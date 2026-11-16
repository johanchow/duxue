"""Offline-only file loading, integrity and quota checks. No application imports."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from evals.dialogue import EpisodeRecord, TurnRecord

CATEGORIES = {"subject_competence", "diagnostic_reasoning", "pedagogical_action"}
TARGETS = {
    "subject_competence": 42,
    "diagnostic_reasoning": 71,
    "pedagogical_action": 96,
}
SUBJECTS = {
    "chinese": 30,
    "math": 30,
    "english": 30,
    **dict.fromkeys(("physics", "chemistry", "biology", "politics", "history"), 20),
    "geography": 19,
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"missing or unsafe dataset file: {name}")
    return path


def load(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["schema_version"] != "local-eval-manifest.v1":
        raise ValueError("unsupported local manifest")
    for name, checksum in manifest["files"].items():
        if sha(inside(root, name)) != checksum:
            raise ValueError(f"dataset hash mismatch: {name}")
    remote_assets = manifest.get("assets")
    if remote_assets is not None:
        from evals.local.assets import validate_reference

        if "assets.oss.json" not in manifest["files"] or json.loads(
            inside(root, "assets.oss.json").read_text()
        ) != remote_assets:
            raise ValueError("unhashed or inconsistent OSS asset registry")
        for name, ref in remote_assets.items():
            validate_reference(name, ref)
            if manifest["files"].get("assets/" + name) != ref["sha256"]:
                raise ValueError("OSS reference differs from original image digest")
    tasks, ids = [], set()
    for entry in manifest["tasks"]:
        if any(entry[k] not in manifest["files"] for k in ("record", "source_record")):
            raise ValueError("unhashed task or source file")
        raw = json.loads(inside(root, entry["record"]).read_text())
        record = (
            EpisodeRecord if raw["type"] == "episode" else TurnRecord
        ).model_validate(raw)
        if record.id != entry["id"] or record.id in ids:
            raise ValueError("duplicate or inconsistent case id")
        ids.add(record.id)
        if entry["category"] not in CATEGORIES:
            raise ValueError("excluded evaluation category")
        if entry["subject"] not in SUBJECTS or entry["level"] not in {
            "gaokao_equivalent",
            "other_k12",
            "unknown",
        }:
            raise ValueError("invalid subject or level")
        if entry["execution_target"] not in {"solve", "tutoring"}:
            raise ValueError("invalid execution target")
        expected_dataset = (
            "guidance-logic"
            if entry["category"] == "pedagogical_action"
            else "teaching-correctness"
        )
        if entry["dataset"] != expected_dataset:
            raise ValueError("dataset purpose mismatch")
        if (entry["execution_target"] == "solve") != (
            entry["category"] == "subject_competence"
        ):
            raise ValueError("solution/tutoring target mismatch")
        if entry["split"] not in {"development", "holdout"}:
            raise ValueError("invalid split")
        if (
            not entry["level_review"]["reason"]
            or entry["level_review"]["status"] != "proposed"
        ):
            raise ValueError("missing level review or unsupported certification")
        source = json.loads(inside(root, entry["source_record"]).read_text())
        original = source["record"]
        meta = json.loads(original["extra_info"])
        if meta["category"] not in CATEGORIES:
            raise ValueError("curriculum source excluded")
        if (
            source["revision"] != manifest["source_revision"]
            or source["uid"] != meta["uid"]
        ):
            raise ValueError("source provenance mismatch")
        # Explicit projection: references never become messages or runtime context.
        canonical = json.dumps(original, ensure_ascii=False, sort_keys=True).encode()
        if hashlib.sha256(canonical).hexdigest() != source.get("record_sha256"):
            raise ValueError("upstream source record digest mismatch")
        if source.get("projected_messages") != raw["messages"]:
            raise ValueError("runtime messages differ from reviewed input projection")
        original_question = original["messages"][1]["content"]
        if any(
            c.input_snapshot.context.problem is None
            or c.input_snapshot.context.problem.summary != original_question
            for c in record.checks
        ):
            raise ValueError(
                "runtime context differs from original question projection"
            )
        if any(
            c.grading.reference_response != original["messages"][-1]["content"]
            for c in record.checks
        ):
            raise ValueError("scoring reference differs from original source")
        if not source.get("adaptation"):
            raise ValueError("missing source adaptation review")
        if record.type == "single_turn" and len(record.messages) - 1 > 8:
            raise ValueError("history would be silently truncated")
        for check in record.checks:
            if check.grading.native_evaluators:
                raise ValueError("cloud-only evaluator in local dataset")
            if not check.grading.reference_response:
                raise ValueError("missing independent scoring reference")
        for message in record.messages:
            for name in message.images:
                asset = inside(root, "assets/" + name)
                if (
                    "assets/" + name not in manifest["files"]
                    or not asset.stat().st_size
                ):
                    raise ValueError("unverified image")
        if remote_assets is not None:
            names = {n for m in record.messages for n in m.images}
            if not names <= remote_assets.keys() or entry.get("assets") != {
                name: remote_assets[name] for name in sorted(names)
            }:
                raise ValueError("missing or inconsistent task OSS reference")
        tasks.append((entry, record))
    return manifest, tasks


def validate(root):
    manifest, tasks = load(root)
    entries = [e for e, _ in tasks]
    categories = Counter(e["category"] for e in entries)
    subjects = Counter(e["subject"] for e in entries)
    high = sum(e["level"] == "gaokao_equivalent" for e in entries)
    gaps = []
    for key, target in TARGETS.items():
        if categories[key] != target:
            gaps.append(f"{key}: {categories[key]}/{target}")
    for key, target in SUBJECTS.items():
        if subjects[key] != target:
            gaps.append(f"{key}: {subjects[key]}/{target}")
        dims = Counter(e["category"] for e in entries if e["subject"] == key)
        expected = dict(
            zip(
                ("subject_competence", "diagnostic_reasoning", "pedagogical_action"),
                (6, 10, 14)
                if target == 30
                else ((4, 6, 9) if target == 19 else (4, 7, 9)),
            )
        )
        if dict(dims) != expected:
            gaps.append(f"{key} dimension allocation: {dict(dims)} expected {expected}")
    high_categories = Counter(
        e["category"] for e in entries if e["level"] == "gaokao_equivalent"
    )
    for category, minimum in {
        "subject_competence": 21,
        "diagnostic_reasoning": 36,
        "pedagogical_action": 48,
    }.items():
        if high_categories[category] < minimum:
            gaps.append(f"gaokao {category}: {high_categories[category]}/{minimum}")
    if high < 105:
        gaps.append(f"gaokao-level: {high}/105")
    families = defaultdict(set)
    for e in entries:
        families[e["family_id"]].add(e["split"])
    if any(len(s) > 1 for s in families.values()):
        raise ValueError("problem family crosses development/holdout split")
    return {
        "structural_status": "passed",
        "acceptance_status": "incomplete" if gaps else "passed",
        "tasks": len(entries),
        "unique_problem_families": len(families),
        "categories": dict(categories),
        "subjects": dict(subjects),
        "gaokao_level_proposed": high,
        "gaokao_level_teacher_confirmed": 0,
        "gaokao_by_category": dict(high_categories),
        "gaokao_by_subject": dict(
            Counter(e["subject"] for e in entries if e["level"] == "gaokao_equivalent")
        ),
        "image_tasks": sum(bool(m.images) for _, r in tasks for m in r.messages),
        "episodes": sum(r.type == "episode" for _, r in tasks),
        "checkpoints": sum(len(r.checks) for _, r in tasks),
        "split_counts": dict(Counter(e["split"] for e in entries)),
        "gaps": gaps,
        "data_digest": sha(Path(root) / "manifest.json"),
        "source_revision": manifest["source_revision"],
        "image_storage": "oss" if "assets" in manifest else "local",
        "oss_images": len(manifest.get("assets", {})),
    }


def select(tasks, args):
    found = []
    for entry, record in tasks:
        if any(
            getattr(args, key, None) and entry[key] not in getattr(args, key)
            for key in ("dataset", "subject", "level", "split")
        ):
            continue
        if args.case and entry["id"] not in args.case:
            continue
        found.append((entry, record))
    if not found or (args.case and set(args.case) - {e["id"] for e, _ in found}):
        raise ValueError("no matching tasks or requested cases missing")
    return found
