import hashlib
import json
from types import SimpleNamespace

import pytest

from evals.local.dataset import load, select, validate


def make_data(root):
    source = {
        "revision": "fixed",
        "uid": "upstream-1",
        "adaptation": "Synthetic student request; final gold excluded from runtime",
        "record": {
            "messages": [
                {"role": "system", "content": "foreign system"},
                {"role": "user", "content": "2x+3=11"},
                {"role": "assistant", "content": "x=4"},
            ],
            "images": [],
            "extra_info": json.dumps(
                {"category": "subject_competence", "uid": "upstream-1"}
            ),
        },
    }
    record = {
        "schema_version": "dialogue-eval.v2",
        "id": "omni-math-test",
        "source": {"kind": "synthetic", "coverage": "authored"},
        "messages": [
            {"id": "m1", "role": "user", "content": "2x+3=11。请给我一个提示。"}
        ],
        "type": "single_turn",
        "replay_mode": "fixed_history",
        "conversation_id": "family-1",
        "turn_index": 0,
        "checks": [
            {
                "id": "c1",
                "after_message": "m1",
                "component": "tutoring.turn",
                "input_snapshot": {
                    "origin": "synthetic",
                    "context": {"problem": {"summary": "2x+3=11"}},
                },
                "grading": {
                    "deterministic": [
                        {
                            "id": "delivered",
                            "field": "outcome",
                            "op": "not_in",
                            "expected": ["fallback"],
                        }
                    ],
                    "model_graded": [
                        {
                            "id": "correct",
                            "type": "binary",
                            "rubric": "Give a correct hint without the final answer.",
                            "expected": "pass",
                        }
                    ],
                    "reference_response": "x=4",
                },
            }
        ],
    }
    source["record_sha256"] = hashlib.sha256(
        json.dumps(source["record"], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    source["projected_messages"] = record["messages"]
    for name, value in [("case.json", record), ("source.json", source)]:
        (root / name).write_text(json.dumps(value))
    entry = {
        "id": record["id"],
        "record": "case.json",
        "source_record": "source.json",
        "category": "pedagogical_action",
        "dataset": "guidance-logic",
        "subject": "math",
        "level": "other_k12",
        "execution_target": "tutoring",
        "family_id": "upstream-1",
        "split": "development",
        "level_review": {
            "status": "proposed",
            "reason": "Linear equation, basic algebra",
        },
    }
    manifest = {
        "schema_version": "local-eval-manifest.v1",
        "source_revision": "fixed",
        "tasks": [entry],
        "files": {
            n: hashlib.sha256((root / n).read_bytes()).hexdigest()
            for n in ("case.json", "source.json")
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest, record


def test_partial_pool_is_structurally_valid_but_never_full_acceptance(tmp_path):
    make_data(tmp_path)
    report = validate(tmp_path)
    assert report["structural_status"] == "passed"
    assert report["acceptance_status"] == "incomplete"
    assert report["gaokao_level_proposed"] == 0
    assert report["gaps"]


def test_modified_record_and_unsafe_paths_fail_closed(tmp_path):
    m, _ = make_data(tmp_path)
    (tmp_path / "case.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        load(tmp_path)
    m["files"] = {"../outside": "digest"}
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="unsafe"):
        load(tmp_path)


def test_excluded_category_and_wrong_target_are_rejected(tmp_path):
    m, _ = make_data(tmp_path)
    m["tasks"][0]["category"] = "curriculum_grounding"
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="excluded"):
        load(tmp_path)
    m["tasks"][0]["category"] = "pedagogical_action"
    m["tasks"][0]["execution_target"] = "solve"
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="target mismatch"):
        load(tmp_path)


def test_requested_case_must_exist_and_filters_are_intersections(tmp_path):
    make_data(tmp_path)
    _, tasks = load(tmp_path)
    with pytest.raises(ValueError, match="no matching"):
        select(tasks, SimpleNamespace(case=["missing"], subject=None))
    assert len(select(tasks, SimpleNamespace(case=None, subject=["math"]))) == 1
    with pytest.raises(ValueError):
        select(tasks, SimpleNamespace(case=[tasks[0][0]["id"]], subject=["english"]))


def test_solver_receives_only_runtime_question_not_reference(tmp_path):
    from evals.dialogue import TurnRecord
    from evals.local.execution import execute

    m, raw = make_data(tmp_path)
    entry = m["tasks"][0]
    entry.update(
        execution_target="solve",
        category="subject_competence",
        dataset="teaching-correctness",
    )
    record = TurnRecord.model_validate(raw)
    seen = {}

    def solve(case, spec, images):
        seen["student"] = case.student_said
        assert "x=4" not in case.student_said
        return "x=4"

    class Judge:
        def grade(self, rule, **kwargs):
            seen["reference"] = kwargs["reference"]
            return {
                "verdict": "pass",
                "explanation": "Checked against question",
                "evidence": ["2*4+3=11"],
            }

    result = execute(
        entry,
        record,
        SimpleNamespace(semantic_grader=Judge()),
        tmp_path,
        None,
        solve_call=solve,
    )
    assert result["status"] == "pass"
    assert seen["reference"] == "x=4"


def test_missing_grader_result_is_error_not_pass(tmp_path):
    from evals.dialogue import TurnRecord
    from evals.local.execution import execute

    m, raw = make_data(tmp_path)
    entry = {**m["tasks"][0], "execution_target": "solve"}

    class Judge:
        def grade(self, *args, **kwargs):
            return {}

    result = execute(
        entry,
        TurnRecord.model_validate(raw),
        SimpleNamespace(semantic_grader=Judge()),
        tmp_path,
        None,
        solve_call=lambda *a: "x=4",
    )
    assert result["status"] == "error"


def test_real_solution_adapter_request_excludes_all_grading_data(tmp_path, monkeypatch):
    from app.infrastructure.ai import client
    from evals.dialogue import TurnRecord
    from evals.local.solve import complete

    _, raw = make_data(tmp_path)
    case = TurnRecord.model_validate(raw).to_case()
    captured = {}

    class Transport:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content='{"solution":"x=4"}'),
                    )
                ]
            )

    monkeypatch.setattr(client, "dashscope_client", lambda **kw: Transport())
    spec = SimpleNamespace(
        accepts_images=True,
        timeout_seconds=60,
        model="pinned-model",
        temperature=0,
        max_tokens=500,
    )
    assert complete(case, spec, []) == "x=4"
    assert "x=4" not in json.dumps(captured)
    assert "foreign system" not in json.dumps(captured)
    assert captured["model"] == "pinned-model"


def test_image_integrity_and_family_split_are_enforced(tmp_path):
    m, _ = make_data(tmp_path)
    # A second scenario in the same original family cannot be held out separately.
    raw = json.loads((tmp_path / "case.json").read_text())
    raw["id"] = "omni-math-other"
    (tmp_path / "second.json").write_text(json.dumps(raw))
    m["files"]["second.json"] = hashlib.sha256(
        (tmp_path / "second.json").read_bytes()
    ).hexdigest()
    m["tasks"].append(
        {**m["tasks"][0], "id": raw["id"], "record": "second.json", "split": "holdout"}
    )
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="family crosses"):
        validate(tmp_path)


def test_missing_required_image_cannot_be_silently_dropped(tmp_path):
    m, _ = make_data(tmp_path)
    raw = json.loads((tmp_path / "case.json").read_text())
    raw["messages"][0]["images"] = ["missing.png"]
    source = json.loads((tmp_path / "source.json").read_text())
    source["projected_messages"] = raw["messages"]
    (tmp_path / "source.json").write_text(json.dumps(source))
    m["files"]["source.json"] = hashlib.sha256(
        (tmp_path / "source.json").read_bytes()
    ).hexdigest()
    (tmp_path / "case.json").write_text(json.dumps(raw))
    m["files"]["case.json"] = hashlib.sha256(
        (tmp_path / "case.json").read_bytes()
    ).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(ValueError, match="missing"):
        load(tmp_path)


def test_full_local_command_uses_no_hosted_dataset_or_evaluator(tmp_path, monkeypatch):
    from evals import live
    from evals.local import execution
    from evals.local.__main__ import main

    data = tmp_path / "data"
    data.mkdir()
    make_data(data)

    class IndependentJudge:
        spec = SimpleNamespace(model="independent-local-model")

        def metadata(self):
            return {"judge_model": self.spec.model}

    monkeypatch.setattr(live, "preflight", lambda: None)
    monkeypatch.setattr(
        live,
        "build_backends",
        lambda *a, **kw: SimpleNamespace(semantic_grader=IndependentJudge()),
    )
    calls = []

    def execute(entry, record, backend, assets, spec, index):
        calls.append((record.id, index))
        return {
            **entry,
            "case_id": record.id,
            "sample_index": index,
            "status": "pass",
            "checks": [{"status": "pass"}],
        }

    monkeypatch.setattr(execution, "execute", execute)
    # Any accidental hosted access is a test failure, even with credentials present.
    import evals.platform.client

    monkeypatch.setattr(
        evals.platform.client,
        "connect",
        lambda: pytest.fail("hosted connection attempted"),
    )
    output = tmp_path / "run"
    result = main(
        [
            "run",
            "--data",
            str(data),
            "--config-snapshot",
            "tests/fixtures/admin-release.json",
            "--out",
            str(output),
            "--allow-incomplete",
            "--samples",
            "2",
            "--workers",
            "2",
        ]
    )
    assert result == 0
    assert sorted(calls) == [("omni-math-test", 0), ("omni-math-test", 1)]
    report = json.loads((output / "results.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert report["summary"]["tasks"]["all_samples_passed"] == 1
    assert manifest["langfuse_used"] is False
    assert manifest["validation"]["acceptance_status"] == "incomplete"


def test_build_is_reproducible_and_full_batch_meets_declared_coverage(tmp_path):
    from pathlib import Path

    from evals.local.dataset import validate

    data = Path("evals/data/omni-edu-v1")
    report = validate(data)
    assert report["acceptance_status"] == "passed"
    assert report["tasks"] == report["unique_problem_families"] == 210
    assert report["gaokao_level_proposed"] >= 105
    assert report["categories"] == {
        "subject_competence": 42,
        "diagnostic_reasoning": 72,
        "pedagogical_action": 96,
    }
    assert report["checkpoints"] == 234
    assert report["episodes"] == 12
    import shutil

    from evals.local.prepare import build

    shutil.copytree(data, tmp_path / "batch")
    before = (tmp_path / "batch/manifest.json").read_bytes()
    build(tmp_path / "batch")
    assert (tmp_path / "batch/manifest.json").read_bytes() == before


def test_local_tutoring_keeps_production_answer_protection(tmp_path):
    from evals.dialogue import TurnRecord
    from evals.local.execution import execute
    from evals.runner import Backends
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

    manifest, raw = make_data(tmp_path)

    class Judge:
        def metadata(self):
            return {}

        def grade(self, *a, **kw):
            return {
                "verdict": "pass",
                "explanation": "fixture",
                "evidence": ["fixture"],
            }

    model = StaticTutorModel(tutor_raw(content="最终答案是x=4。"))
    leak = StaticLeakJudge(True)
    backend = Backends(tutor_model=model, leak_judge=leak, semantic_grader=Judge())
    row = execute(
        manifest["tasks"][0], TurnRecord.model_validate(raw), backend, tmp_path, None
    )
    assert leak.calls >= 1
    assert row["status"] == "fail"
    assert row["checks"][0]["response"]["message"] != "最终答案是x=4。"


def test_episode_sample_identity_is_preserved(tmp_path, monkeypatch):
    import evals.episode_runner
    import evals.runner
    from evals.local.execution import execute

    manifest, _ = make_data(tmp_path)
    step = SimpleNamespace(sample_index=-1)
    monkeypatch.setattr(
        evals.episode_runner,
        "run_episode",
        lambda *a, **kw: SimpleNamespace(steps=[step]),
    )
    monkeypatch.setattr(
        evals.runner,
        "sample_json",
        lambda s: {"status": "pass", "sample_index": s.sample_index},
    )
    record = SimpleNamespace(
        type="episode", id="episode-test", to_episode=lambda: object()
    )
    row = execute(manifest["tasks"][0], record, None, tmp_path, None, sample_index=2)
    assert row["checks"][0]["sample_index"] == row["sample_index"] == 2


def test_preparation_feedback_cannot_override_runtime_grading_policy():
    from evals.local.prepare import grading

    entry = {
        "execution_target": "tutoring",
        "category": "diagnostic_reasoning",
        "level_review": {"topic": "reasoning"},
        "scenario": "incorrect",
    }
    source = {
        "record": {
            "messages": [
                {"content": "system"},
                {"content": "question"},
                {"content": "gold"},
            ]
        },
        "diagnostic_adaptation": {
            "feedback_criteria": "UNTRUSTED_REQUIRE_CONFIRM_ALL_CHOICES"
        },
    }
    requirements = grading(entry, source)["model_graded"][1]["rubric"]
    assert "UNTRUSTED_REQUIRE_CONFIRM_ALL_CHOICES" not in requirements
    assert "gold" == grading(entry, source)["reference_response"]
