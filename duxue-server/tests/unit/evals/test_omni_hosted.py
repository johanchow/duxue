import json
from pathlib import Path
from types import SimpleNamespace as Obj

import pytest

from evals.platform.omni import project
from evals.platform.protocol import hydrate

ROOT = Path("evals/data/omni-edu-v1")


def test_all_batch_projections_roundtrip_and_solve_scores_are_separate():
    rows = project(ROOT)
    assert len(rows) == 209 == len({r["id"] for r in rows})
    assert sum(r["dataset_name"] == "teaching-correctness" for r in rows) == 113
    for row in rows:
        record = hydrate(Obj(**{**row, "expected_output": row["expected_output"]}))
        assert row["metadata"]["batch"] == "omni-edu-v1"
        assert row["metadata"]["source_revision"]
        assert record["id"] == row["metadata"]["case_id"]
        for c in record["checks"]:
            assert "grading" not in next(
                x for x in row["input"]["record"]["checks"] if x["id"] == c["id"]
            )
        if row["input"]["execution_target"] == "solve":
            for spec in row["expected_output"]["checks"].values():
                assert set(spec["evaluators"]) == {
                    "eval.deterministic_pass",
                    "eval.teaching_correctness",
                    "eval.case_requirements",
                }
        else:
            assert (
                "eval.guidance_logic"
                in record["checks"][0]["grading"]["native_evaluators"]
            )
    assert sum(bool(r["input"]["assets"]) for r in rows) == 17
    assert sum(bool(r["metadata"].get("known_issues")) for r in rows) == 1
    assert project(ROOT) == rows


def test_oss_materializer_never_uses_langfuse_media(tmp_path, monkeypatch):
    from evals.local import assets
    from evals.platform.execution import materialize_assets
    from tests.unit.evals.test_oss_assets import DATA, NAME, REF, Bucket

    bucket = Bucket()
    bucket.objects[REF["key"]] = DATA
    monkeypatch.setattr(assets, "connect_bucket", lambda: bucket)
    item = Obj(input={"assets": {NAME: REF}})
    client = Obj(resolve_media_references=lambda **kw: pytest.fail("native media used"))
    materialize_assets(client, item, tmp_path)
    assert (tmp_path / NAME).read_bytes() == DATA
    bucket.objects[REF["key"]] = b"bad"
    with pytest.raises(ValueError, match="integrity"):
        materialize_assets(client, item, tmp_path)


def test_execution_dispatches_solve_without_tutoring_or_local_grading(
    tmp_path, monkeypatch
):
    from evals.platform import execution

    row = next(
        r
        for r in project(ROOT)
        if r["input"]["execution_target"] == "solve" and not r["input"]["assets"]
    )
    item = Obj(**row)
    calls = []
    monkeypatch.setattr(
        execution,
        "solve_turn",
        lambda case, backend, assets: (
            {"outcome": "answer", "tool_calls": []},
            {"response": {"message": "solution"}},
            1,
            None,
        ),
    )
    monkeypatch.setattr(
        execution, "turn", lambda *a: pytest.fail("Ward tutor used for internal solve")
    )

    class Scorer:
        def evaluate(self, **kw):
            calls.append(kw)
            return {"status": "pass", "check_id": kw["check_id"]}

    result = execution.execute_item(None, item, Scorer(), {"tutoring.turn": None})
    assert result["status"] == "pass"
    assert calls[0]["evidence"]["response"]["message"] == "solution"


def test_signed_images_replace_data_uris_in_runtime_and_evidence(tmp_path, monkeypatch):
    from evals import runner
    from evals.dialogue import TurnRecord
    from evals.local import assets
    from evals.outcome import Observation
    from evals.platform import execution
    from tests.unit.evals.test_oss_assets import DATA, NAME, REF

    (tmp_path / NAME).write_bytes(DATA)
    # A genuine case, adapted only to the isolated image fixture.
    row = next(
        r
        for r in project(ROOT)
        if r["input"]["execution_target"] == "tutoring"
        and r["input"]["record"]["type"] == "single_turn"
    )
    row["input"]["record"]["messages"][0]["images"] = [NAME]
    record = hydrate(Obj(**row))
    case = TurnRecord.model_validate(record).to_case()
    url = "https://example.test/private.png?signature=temporary"
    monkeypatch.setattr(assets, "signed_urls", lambda refs: {NAME: url})

    def observe(case, backend, window, images, **kw):
        assert images == [url]
        return Observation(
            "hint_like", content="hint", delivered_content="hint", tool_calls=[]
        )

    monkeypatch.setattr(runner, "_observe_tutor", observe)
    with execution.external_assets({NAME: REF}):
        _, evidence, _, _ = execution.turn(case, None, tmp_path)
    assert evidence["images"] == [{"name": NAME, "image": url}]
    assert "data:image" not in json.dumps(evidence)


def test_import_guard_rejects_remote_edits_including_asset_or_archive_changes():
    import copy

    from evals.platform.omni import assert_unchanged

    row = next(r for r in project(ROOT) if r["input"]["assets"])
    remote = {
        "input": row["input"],
        "expectedOutput": row["expected_output"],
        "metadata": row["metadata"],
        "status": "ACTIVE",
    }
    assert_unchanged(remote, row)
    changed = copy.deepcopy(remote)
    next(iter(changed["input"]["assets"].values()))["key"] = "elsewhere"
    with pytest.raises(ValueError, match="refusing overwrite"):
        assert_unchanged(changed, row)
    with pytest.raises(ValueError, match="refusing overwrite"):
        assert_unchanged({**remote, "status": "ARCHIVED"}, row)


def test_batch_and_case_selection_excludes_other_batches_and_archived_items():
    from evals.platform.__main__ import select_items

    def item(case, batch, status="ACTIVE"):
        return Obj(
            status=status, metadata={"batch": batch}, input={"record": {"id": case}}
        )

    items = [
        item("one", "omni-edu-v1"),
        item("two", "legacy"),
        item("three", "omni-edu-v1", "ARCHIVED"),
        Obj(
            status="ACTIVE",
            metadata={"batch": "guardian-regression"},
            input={"execution_target": "guardian_explain", "record": {"id": "four"}},
        ),
    ]
    assert select_items(items, batch=["omni-edu-v1"]) == [items[0]]
    assert select_items(items, batch=["omni-edu-v1"], cases={"two"}) == []
    assert select_items(items) == items[:2]
    assert select_items(items, batch=["guardian-regression"]) == []


def test_solve_cannot_silently_receive_tutoring_scores():
    row = next(r for r in project(ROOT) if r["input"]["execution_target"] == "solve")
    next(iter(row["expected_output"]["checks"].values()))["evaluators"][
        "eval.guidance_logic"
    ] = {"min": 4}
    with pytest.raises(ValueError, match="dimensions mismatch"):
        hydrate(Obj(**row))
