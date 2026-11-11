"""Transport/projection only. Scoring definitions live in Langfuse."""

from __future__ import annotations
import copy
import hashlib
import json
import uuid

VERSION = "duxue-dataset.v1"
NAMESPACE = uuid.UUID("830a4b00-a6bb-4d16-84a1-0ac726a09d60")


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def item_id(case_id):
    return str(uuid.uuid5(NAMESPACE, case_id))


def convert(record, category):
    """One dialogue per item; expected checks are never application input."""
    record = copy.deepcopy(record)
    expected = {
        "checks": {},
        "reference_problem": record.pop("reference_problem", None),
    }
    for check in record["checks"]:
        grading = check.pop("grading")
        semantic = grading.get("model_graded", [])
        evaluators = {"eval.deterministic_pass": {"equals": True}}
        if semantic:
            # The previous mixed quality dimension becomes two explicit dimensions.
            evaluators.update(
                {
                    "eval.teaching_correctness": {"min": 4},
                    "eval.guidance_logic": {"min": 4},
                    "eval.case_requirements": {"equals": True},
                }
            )
            if check["component"] == "tutoring.turn":
                evaluators["eval.answer_protection"] = {"equals": True}
                evaluators["eval.safety"] = {"equals": True}
        expected["checks"][check["id"]] = {
            "deterministic": grading["deterministic"],
            "case_criteria": [r["rubric"] for r in semantic if r.get("rubric")],
            "reference_response": grading.get("reference_response"),
            "rationale": grading.get("rationale", []),
            "evaluators": evaluators,
        }
    return {
        "id": item_id(record["id"]),
        "input": {"schema_version": VERSION, "record": record, "assets": {}},
        "expected_output": expected,
        "metadata": {
            "case_id": record["id"],
            "category": category,
            "review_batch": record.get("review_batch"),
            "label_status": record["label_status"],
            "migration_digest": digest([record, expected]),
            "schema_version": VERSION,
        },
    }


def hydrate(item):
    payload = item.input
    if payload.get("schema_version") != VERSION:
        raise ValueError("unsupported remote dataset schema")
    record = copy.deepcopy(payload["record"])
    expected = item.expected_output
    if set(expected["checks"]) != {c["id"] for c in record["checks"]}:
        raise ValueError("expected checks do not match input checkpoints")
    for check in record["checks"]:
        spec = expected["checks"][check["id"]]
        if (
            not spec.get("evaluators")
            or "eval.deterministic_pass" not in spec["evaluators"]
        ):
            raise ValueError("missing required native evaluators")
        for name, threshold in spec["evaluators"].items():
            if not (
                isinstance(threshold, dict)
                and (
                    (set(threshold) == {"equals"} and type(threshold["equals"]) is bool)
                    or (
                        set(threshold) == {"min"}
                        and type(threshold["min"]) is int
                        and 1 <= threshold["min"] <= 5
                    )
                )
            ):
                raise ValueError(f"invalid remote evaluator threshold: {name}")
        if check["component"] == "tutoring.turn" and not {
            "eval.teaching_correctness",
            "eval.guidance_logic",
        } <= set(spec["evaluators"]):
            raise ValueError("teaching responses require native semantic evaluators")
        # Projection schema only: legacy grade_result is never executed by this runner.
        check["grading"] = {
            "deterministic": spec["deterministic"],
            "model_graded": [],
            "native_evaluators": list(spec["evaluators"]),
            "reference_response": spec.get("reference_response"),
        }
    if record["type"] == "judge":
        record["reference_problem"] = expected.get("reference_problem")
    from evals.migrate import validate_record

    validate_record(record)
    return record


def asset_names(record):
    names = set()

    def visit(value):
        if isinstance(value, dict):
            names.update(value.get("images", []))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(record)
    return sorted(names)


def summarize_scores(required, scores):
    """Apply remotely stored thresholds; missing/duplicate scores are errors."""
    if not required:
        return {"status": "error", "grades": [], "error": "missing_required_evaluators"}
    results = []
    for name, threshold in required.items():
        found = [s for s in scores if s["name"] == name and s.get("source") == "EVAL"]
        if len(found) != 1:
            results.append(
                {
                    "name": name,
                    "status": "error",
                    "reason": "missing_or_duplicate_score",
                }
            )
            continue
        s = found[0]
        value = s.get("value")
        if "min" in threshold:
            valid = (
                type(value) in (int, float) and 1 <= value <= 5 and value == int(value)
            )
            passed = valid and value >= threshold["min"]
        else:
            valid = type(value) in (bool, int, float) and value in (0, 1)
            passed = valid and bool(value) == threshold["equals"]
        results.append(
            {
                "name": name,
                "status": ("pass" if passed else "fail") if valid else "error",
                "score_id": s.get("id"),
                "value": value,
                "comment": s.get("comment"),
                "metadata": s.get("metadata"),
            }
        )
    statuses = {g["status"] for g in results}
    return {
        "status": "error"
        if "error" in statuses
        else "fail"
        if "fail" in statuses
        else "pass",
        "grades": results,
        "calibration_status": "uncalibrated",
        "quality_passed": None,
    }
