"""The disk contract must preserve evidence and checkpoint boundaries."""

import copy
import json

import pytest

from evals import dataset, export


def test_guard_seed_uses_a_real_message_envelope_without_fabricated_history():
    data = dataset.read_object(
        dataset.DATA_DIR / "answer-protection-safety/turn-guard-01.json"
    )
    assert data["schema_version"] == "dialogue-eval.v2"
    assert data["source"]["kind"] == "synthetic"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "user"
    assert data["checks"][0]["after_message"] == data["messages"][0]["id"]
    assert data["checks"][0]["input_snapshot"]["origin"] == "synthetic"
    assert not {"history", "student_said", "context", "expect"} & data.keys()


def test_export_keeps_picture_only_turn_and_does_not_infer_state_from_future():
    from app.application.workflows.tutor_turn import REMINDER

    rows = [
        {
            "turn_id": "t1",
            "author": "ward",
            "text": "",
            "attachment_refs": ["camera.jpg"],
        },
        {
            "turn_id": "t2",
            "author": "companion",
            "text": REMINDER,
            "attachment_refs": [],
        },
    ]
    records = export.build_cases(
        rows,
        conversation_id="example",
        component="tutoring.turn",
        asset_for=lambda _: "img-abc.jpg",
    )
    assert len(records) == 1
    record = records[0].model_dump(mode="json")
    assert record["messages"] == [
        {
            "id": "m1",
            "role": "user",
            "content": "",
            "images": ["img-abc.jpg"],
            "image_target_refs": [],
        }
    ]
    snapshot = record["checks"][0]["input_snapshot"]
    assert snapshot["origin"] == "missing" and snapshot["context"] is None


def _turn_record():
    from evals.dialogue import TurnRecord

    return TurnRecord.model_validate(
        dataset.read_object(dataset.DATA_DIR / "answer-protection-safety/turn-guard-01.json")
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "assistant_target",
        "unknown_target",
        "expect_in_message",
        "asset_path",
        "old_field",
    ],
)
def test_turn_contract_rejects_ambiguous_or_mixed_formats(mutation):
    from evals.dialogue import TurnRecord

    data = _turn_record().model_dump(mode="json")
    if mutation == "duplicate":
        data["messages"].append(copy.deepcopy(data["messages"][0]))
    elif mutation == "assistant_target":
        data["messages"][0]["role"] = "assistant"
    elif mutation == "unknown_target":
        data["checks"][0]["after_message"] = "absent"
    elif mutation == "expect_in_message":
        data["messages"][0]["expect"] = {"answer": "4"}
    elif mutation == "asset_path":
        data["messages"][0]["images"] = ["../private.jpg"]
    else:
        data["student_said"] = "legacy input must not silently override messages"
    with pytest.raises(ValueError):
        TurnRecord.model_validate(data)


def test_fixed_checkpoint_does_not_receive_future_messages_or_reference_answer(
    tmp_path,
):
    from evals.dialogue import TurnRecord
    from tests.support.eval_cases import Backends
    from evals.runner import run_cases
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw

    data = _turn_record().model_dump(mode="json")
    data["messages"].extend(
        [
            {
                "id": "m2",
                "role": "assistant",
                "content": "DO NOT LEAK THIS FUTURE ANSWER",
            },
            {"id": "m3", "role": "user", "content": "NEXT USER MESSAGE"},
        ]
    )
    data["checks"][0]["grading"]["model_graded"][0] = {
        "id": "hidden",
        "type": "score",
        "rubric": "HIDDEN LABEL",
        "min_score": 4,
    }
    data["checks"][0]["grading"]["reference_response"] = "REFERENCE RESPONSE"
    case = TurnRecord.model_validate(data).to_case()
    model = StaticTutorModel(tutor_raw("guide", "先观察等号两侧。"))
    run_cases(
        [case],
        {
            "tutoring.turn": Backends(
                tutor_model=model, leak_judge=StaticLeakJudge(False)
            )
        },
        samples=1,
        assets_dir=tmp_path,
    )
    assert model.calls and all(c["recent_utterances"] == [] for c in model.calls)
    assert all(
        token not in str(model.calls)
        for token in ("DO NOT LEAK", "NEXT USER", "HIDDEN LABEL", "REFERENCE RESPONSE")
    )


def test_missing_snapshot_skips_without_invoking_model_even_if_fallback_is_allowed(
    tmp_path,
):
    from evals.dialogue import TurnRecord
    from tests.support.eval_cases import Backends
    from evals.runner import run_cases, run_sample
    from tests.support.fakes import StaticTutorModel, tutor_raw

    data = _turn_record().model_dump(mode="json")
    data["checks"][0]["input_snapshot"] = {"origin": "missing", "context": None}
    data["checks"][0]["grading"]["deterministic"] = [
        {"id": "kind", "field": "outcome", "op": "in", "expected": ["fallback"]}
    ]
    case = TurnRecord.model_validate(data).to_case()
    model = StaticTutorModel(tutor_raw())
    backend = Backends(tutor_model=model)
    result = run_cases(
        [case], {"tutoring.turn": backend}, samples=1, assets_dir=tmp_path
    )[0]
    assert result.status == "skipped" and result.skip_reason == "missing_input_snapshot"
    assert not run_sample(case, backend, [], []).passed
    assert model.calls == []


def test_export_same_turn_user_and_assistant_have_distinct_message_ids_and_image_refs():
    rows = [
        {
            "turn_id": "same-turn",
            "author": "ward",
            "text": "看图",
            "attachment_refs": ["image.jpg"],
        },
        {
            "turn_id": "same-turn",
            "author": "companion",
            "text": "原回复",
            "attachment_refs": [],
            "image_target_refs": ["image-ref"],
        },
        {
            "turn_id": "next-turn",
            "author": "ward",
            "text": "再解释一下",
            "attachment_refs": [],
        },
    ]
    records = export.build_cases(
        rows,
        conversation_id="example",
        component="tutoring.turn",
        asset_for=lambda _: "img-abc.jpg",
    )
    last = records[-1]
    assert [m.id for m in last.messages] == ["m1", "m2", "m3"]
    assert last.messages[1].image_target_refs == ["image-ref"]


def test_export_explicit_snapshot_and_roundtrip_preserve_image_only_request(tmp_path):
    from evals.dialogue import ContextSnapshot

    rows = [
        {
            "turn_id": "t1",
            "author": "ward",
            "text": "",
            "attachment_refs": ["image.jpg"],
        }
    ]
    records = export.build_cases(
        rows,
        conversation_id="example",
        component="tutoring.turn",
        asset_for=lambda _: "img-abc.jpg",
        snapshots={
            "t1": ContextSnapshot(
                origin="recorded",
                references=["observation-1"],
                context={"task_active": True, "problem": {"summary": "原题"}},
            )
        },
    )
    record = records[0]
    path = tmp_path / f"{record.id}.json"
    path.write_text(record.model_dump_json())
    case = dataset.load_cases(path)[0]
    assert case.snapshot_origin == "recorded" and case.context.task_active
    assert case.student_said == "" and case.images == ["img-abc.jpg"]


def test_snapshot_origin_cannot_silently_fabricate_or_discard_context():
    from evals.dialogue import ContextSnapshot

    for fields in (
        {"origin": "missing", "context": {}},
        {"origin": "recorded", "context": {}},
        {"origin": "synthetic", "context": None},
    ):
        with pytest.raises(ValueError):
            ContextSnapshot.model_validate(fields)


def test_all_committed_files_share_contract_and_migration_is_idempotent():
    from evals.migrate import migrate_record, validate_record

    files = sorted(dataset.DATA_DIR.rglob("*.json"))
    assert len(files) == 33
    for path in files:
        raw = dataset.read_object(path)
        assert raw["schema_version"] == "dialogue-eval.v2"
        assert isinstance(raw["source"], dict) and "messages" in raw and "checks" in raw
        assert (
            not {"history", "student_said", "initial_history", "turns", "reply"}
            & raw.keys()
        )
        assert validate_record(raw).id == path.stem
        assert migrate_record(raw) == raw
        assert raw["label_status"] == "proposed" and raw["reviewed_by"] is None


def test_explicit_v1_migration_preserves_evidence_and_requires_authored_semantics():
    from evals.migrate import migrate_record

    target = _turn_record().model_dump(mode="json", by_alias=True)
    old = copy.deepcopy(target)
    old["schema_version"] = "dialogue-eval.v1"
    grading = old["checks"][0].pop("grading")
    old["checks"][0]["expect"] = {
        "outcome_not_in": ["fallback", "answer"],
        "content_not_contains": ["x=4"],
    }
    original = copy.deepcopy(old)
    with pytest.raises(ValueError, match="authored grading required"):
        migrate_record(old)
    migrated = migrate_record(old, {"check-1": grading})
    assert old == original
    for key in ("messages", "source", "label_status", "reviewed_by"):
        assert migrated[key] == target[key]
    assert (
        migrated["checks"][0]["input_snapshot"] == target["checks"][0]["input_snapshot"]
    )


def test_episode_script_rejects_future_order_or_pre_authored_answers():
    from evals.dialogue import EpisodeRecord

    raw = dataset.read_object(
        dataset.DATA_DIR / "guidance-logic/episode-mathdial-balance.json"
    )
    for mutation in ("reorder", "assistant"):
        changed = copy.deepcopy(raw)
        if mutation == "reorder":
            changed["checks"][0], changed["checks"][1] = (
                changed["checks"][1],
                changed["checks"][0],
            )
        else:
            changed["messages"][1]["role"] = "assistant"
        with pytest.raises(ValueError):
            EpisodeRecord.model_validate(changed)


def test_episode_migration_preserves_branches_and_state():
    from evals.migrate import migrate_record

    target = dataset.read_object(
        dataset.DATA_DIR / "guidance-logic/episode-mathdial-balance.json"
    )
    old = copy.deepcopy(target)
    old["schema_version"] = "dialogue-eval.v1"
    authored = {}
    for check in old["checks"]:
        authored[check["id"]] = check.pop("grading")
        check["expect"] = {
            "outcome_in": ["hint_like"],
            "outcome_not_in": ["fallback", "answer"],
        }
    migrated = migrate_record(old, authored)
    assert migrated["messages"] == target["messages"]
    for a, b in zip(migrated["checks"], target["checks"]):
        assert a["input_snapshot"] == b["input_snapshot"]
        assert a.get("student_on") == b.get("student_on")


def test_judge_contract_keeps_candidate_and_reference_outside_visible_messages():
    from evals import judge_boundary
    from evals.dialogue import JudgeRecord

    raw = dataset.read_object(dataset.DATA_DIR / "judge-calibration/atomic-fact.json")
    raw["checks"][0]["input_snapshot"]["current_request"] = "新的实际请求"
    received = []
    judge_boundary.run_cases(
        [JudgeRecord.model_validate(raw).to_case()],
        lambda **kw: received.append(kw) or {"leaks": False, "reason": "none"},
        samples=1,
        workers=1,
    )
    assert (
        json.loads(received[0]["problem_summary"])["current_request"] == "新的实际请求"
    )
    assert raw["reference_problem"] not in str(received)
    raw["checks"][0]["candidate_id"] = "not-found"
    with pytest.raises(ValueError):
        JudgeRecord.model_validate(raw)


def test_cli_validates_each_file_type_and_episode_category(capsys):
    from evals.__main__ import main

    for relative in (
        "answer-protection-safety/turn-guard-01.json",
        "guidance-logic/episode-mathdial-balance.json",
        "judge-calibration/atomic-fact.json",
        "answer-protection-safety/protection-scope-conversation.json",
    ):
        assert main(["validate", "--path", str(dataset.DATA_DIR / relative)]) == 0
    assert main(["validate", "--category", "guidance-logic"]) == 0


def test_hash_changes_with_source_evidence_even_when_model_input_is_equal():
    from evals.dialogue import TurnRecord

    first = _turn_record()
    raw = first.model_dump(mode="json")
    raw["checks"][0]["input_snapshot"]["note"] = "补充来源说明"
    second = TurnRecord.model_validate(raw)
    assert first.to_case().student_said == second.to_case().student_said
    assert dataset.dataset_hash([first.to_case()]) != dataset.dataset_hash(
        [second.to_case()]
    )


def test_episode_projection_preserves_snapshot_origin():
    from evals.dialogue import EpisodeRecord
    from evals.episodes import turn_case

    raw = dataset.read_object(
        dataset.DATA_DIR / "guidance-logic/episode-mathdial-balance.json"
    )
    raw["checks"][0]["input_snapshot"]["origin"] = "reconstructed"
    episode = EpisodeRecord.model_validate(raw).to_episode()
    case = turn_case(episode, 0, [], episode.turns[0].student_said)
    assert case.snapshot_origin == "reconstructed"
    assert case.record_digest == episode.record_digest


def test_reference_response_is_scrub_checked_and_missing_grader_is_error():
    from evals.dialogue import TurnRecord
    from evals.graders import grade_result
    from evals.outcome import Observation

    raw = _turn_record().model_dump(mode="json")
    raw["checks"][0]["grading"]["reference_response"] = "a@b.cn"
    case = TurnRecord.model_validate(raw).to_case()
    assert "email" in dataset.pii_findings(case)
    assert (
        grade_result(case, Observation("hint_like", content="另一种表达")).status
        == "error"
    )


@pytest.mark.parametrize(
    "history",
    [
        [{"author": "system", "text": "不能误改成assistant"}],
        [{"author": "ward", "text": "原话", "unknown_evidence": "不能静默丢失"}],
    ],
)
def test_migration_rejects_unrecognized_history_instead_of_discarding_evidence(history):
    from evals.migrate import migrate_record

    old = {
        "id": "legacy-example",
        "component": "tutoring.turn",
        "conversation_id": "example",
        "turn_index": 1,
        "source": "synthetic",
        "student_said": "当前输入",
        "history": history,
    }
    with pytest.raises(ValueError):
        migrate_record(old)
