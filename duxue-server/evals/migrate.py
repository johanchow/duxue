"""Explicit v1 -> v2 migration using authored semantic rules, never inferred keywords.

python -m evals.migrate INPUT --grading-from REVIEWED_V2_DIRECTORY [--write]
Current v2 files only need validation. Old input is preserved unless --write is explicit.
"""

from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path

from evals.grading import Grading


def structural(expect, component):
    """Translate closed assertions only. Semantic expectations need authored rubrics."""
    known = {
        "criteria",
        "response",
        "outcome_in",
        "outcome_not_in",
        "intent_in",
        "answer_protected",
        "visual",
        "visual_kind_in",
        "selected_images",
        "review_conclusion",
        "exit_gate",
        "leaks",
        "reason",
        "reason_in",
        "min_lessons",
        "lesson_source_contains_any",
        "lesson_source_contains_all",
        "content_contains_any",
        "content_not_contains",
        "visual_not_contains",
    }
    if set(expect) - known:
        raise ValueError("unknown legacy expectations: " + str(set(expect) - known))
    rules = []

    def add(field, op, value):
        rules.append(
            {
                "id": f"{field.replace('.', '_')}_{op}",
                "field": field,
                "op": op,
                "expected": value,
            }
        )

    if component == "companion.intent":
        if expect.get("intent_in"):
            add("intent", "in", expect["intent_in"])
        else:
            raise ValueError("route expectation needs an authored intent label")
    elif component == "tutoring.turn":
        if expect.get("outcome_in"):
            add("outcome", "in", expect["outcome_in"])
        forbidden = expect.get("outcome_not_in", ["fallback"])
        # Preserve the v1 allow-list precedence when fallback was explicitly allowed.
        forbidden = [v for v in forbidden if v not in expect.get("outcome_in", [])]
        if forbidden:
            add("outcome", "not_in", forbidden)
        if expect.get("visual"):
            add("visual_present", "eq", expect["visual"] == "present")
        if expect.get("visual_kind_in"):
            add("visual_kind", "in", expect["visual_kind_in"])
        if expect.get("selected_images") is not None:
            add("selected_images", "set_eq", expect["selected_images"])
        if expect.get("review_conclusion"):
            add("review_conclusion", "eq", expect["review_conclusion"])
        if expect.get("min_lessons") is not None:
            add("lesson_count", "gte", expect["min_lessons"])
        for field in ("leaks", "reason", "answer_protected"):
            if (
                field in expect.get("exit_gate", {})
                and expect["exit_gate"][field] is not None
            ):
                add("exit_gate." + field, "eq", expect["exit_gate"][field])
    else:
        if type(expect.get("leaks")) is not bool:
            raise ValueError("judge requires leaks label")
        add("leaks", "eq", expect["leaks"])
        if expect.get("reason_in"):
            add("reason", "in", expect["reason_in"])
        elif expect.get("reason") is not None:
            add("reason", "eq", expect["reason"])
    if expect.get("answer_protected") is not None:
        add("answer_protected", "eq", expect["answer_protected"])
    return rules


def validate_record(row):
    from evals.dialogue import EpisodeRecord, JudgeRecord, TurnRecord
    from evals.conversations import ConversationEval

    model = {
        "single_turn": TurnRecord,
        "episode": EpisodeRecord,
        "judge": JudgeRecord,
        "conversation_replay": ConversationEval,
    }.get(row.get("type"))
    if model is None:
        raise ValueError("unknown evaluation type")
    return model.model_validate(row)


def migrate_record(original, grading_by_check=None):
    row = copy.deepcopy(original)
    if row.get("schema_version") == "dialogue-eval.v2":
        validate_record(row)
        return row
    if row.get("schema_version") != "dialogue-eval.v1":
        raise ValueError(
            "migration requires dialogue-eval.v1; older formats need their historical migrator"
        )
    row["schema_version"] = "dialogue-eval.v2"
    for check in row["checks"]:
        expected = check.pop("expect")
        rules = structural(expected, check["component"])
        supplied = (grading_by_check or {}).get(check["id"])
        if supplied is None:
            if check["component"] == "tutoring.turn":
                raise ValueError(
                    f"{row['id']}/{check['id']}: authored grading required; no automatic semantic migration"
                )
            supplied = {
                "deterministic": rules,
                "model_graded": [],
                "rationale": expected.get("criteria", []),
            }
        grading = Grading.model_validate(supplied)
        for required in rules:
            if not any(
                all(
                    c.model_dump(by_alias=True).get(k) == v
                    for k, v in required.items()
                    if k != "id"
                )
                for c in grading.deterministic
            ):
                raise ValueError("migration cannot discard a structural expectation")
        check["grading"] = grading.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
    validate_record(row)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--grading-from", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    authored = {}
    if args.grading_from:
        paths = (
            [args.grading_from]
            if args.grading_from.is_file()
            else sorted(args.grading_from.rglob("*.json"))
        )
        for path in paths:
            row = json.loads(path.read_text())
            validate_record(row)
            if row["id"] in authored:
                raise ValueError("duplicate authored id")
            authored[row["id"]] = {c["id"]: c["grading"] for c in row["checks"]}
    paths = [args.path] if args.path.is_file() else sorted(args.path.rglob("*.json"))
    if not paths:
        raise ValueError("empty dataset")
    changes = []
    for path in paths:
        original = json.loads(path.read_text())
        migrated = migrate_record(original, authored.get(original["id"]))
        if original != migrated:
            changes.append((path, migrated))
    for path, row in changes:
        if args.write:
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    print(
        f"{len(paths)} validated / {len(changes)} {'migrated' if args.write else 'would migrate'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
