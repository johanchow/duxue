"""The dataset is a reviewed artifact. CI checks its shape, not model quality (no network)."""

import pytest

from evals import dataset, episodes
from evals.__main__ import main
from evals.schema import EvalCase


def _case(**fields) -> EvalCase:
    base = {
        "id": "turn-test-00", "component": "tutoring.turn", "conversation_id": "abc12345", "turn_index": 0,
        "student_said": "这个怎么读？", "source": "real", "label_status": "proposed",
    }
    return EvalCase.model_validate({**base, **fields})


def test_committed_dataset_is_valid_and_not_empty():
    cases = dataset.load_cases()
    assert len(cases) == 90
    assert dataset.validate(cases) == []
    assert dataset.validate_layout() == []


def test_each_category_owns_its_cases_and_multi_turn_is_separate():
    expected = {
        "scene_routing": 12, "real_regression": 17, "answer_protection": 12,
        "pronunciation_context": 3, "visual": 10, "fact_vs_reasoning": 12,
        "teaching_quality": 24,
    }
    for category, count in expected.items():
        assert len(dataset.load_cases(dataset.DATA_DIR / category)) == count
    assert len(episodes.load_episodes()) == 24
    assert all(row.label_status == "proposed" for row in episodes.load_episodes())
    assert episodes.validate_episodes(episodes.load_episodes()) == []


def test_layout_rejects_a_case_in_the_wrong_category(tmp_path):
    for category in dataset.CATEGORIES:
        (tmp_path / category).mkdir()
        if category != "multi_turn":
            (tmp_path / category / "cases.jsonl").write_text("", encoding="utf-8")
        else:
            (tmp_path / category / "episodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "scene_routing" / "cases.jsonl").write_text(_case().model_dump_json() + "\n", encoding="utf-8")
    assert any("scene_routing requires companion.intent" in problem
               for problem in dataset.validate_layout(tmp_path))


def test_dataset_covers_the_three_debugged_conversations_and_the_guard_seeds():
    cases = dataset.load_cases()
    conversations = {c.conversation_id for c in cases}
    assert {"ab8f80d3", "97103aaf", "b48b70b3", "4d43c20f", "synthetic"} <= conversations
    assert {c.component for c in cases} == {"tutoring.turn", "companion.intent"}
    assert sum("guard" in c.tags for c in cases) <= 6
    assert all(c.source == "synthetic" for c in cases if "guard" in c.tags)


def test_rubric_slice_covers_several_teaching_angles():
    cases = [c for c in dataset.load_cases() if "rubric" in c.tags]
    angles = {tag for case in cases for tag in case.tags}
    assert {
        "mistake-id", "mistake-loc", "leak-implicit", "guidance", "actionable",
        "socratic", "misdiagnosis", "prerequisite",
    } <= angles
    assert all(case.source == "synthetic" and case.label_status == "proposed" for case in cases)
    assert all("guard" not in case.tags for case in cases)
    assert all(case.expect.is_specific() for case in cases)


def test_ai_written_labels_are_never_confirmed_without_a_human():
    for case in dataset.load_cases():
        if case.label_status == "confirmed":
            assert case.reviewed_by


def test_confirmed_needs_reviewer_and_a_real_expectation():
    problems = dataset.validate([_case(label_status="confirmed")])
    assert any("reviewed_by" in p for p in problems)
    assert any("expectation" in p for p in problems)
    assert dataset.validate([
        _case(label_status="confirmed", reviewed_by="johan", expect={"outcome_in": ["pronounce"]}),
    ]) == []


def test_unconfirmed_case_cannot_carry_a_reviewer():
    assert any("reviewed_by" in p for p in dataset.validate([_case(reviewed_by="johan")]))


def test_duplicate_ids_and_bad_asset_names_are_reported():
    problems = dataset.validate([
        _case(), _case(images=["../secret.jpg"]),
    ])
    assert any("duplicate id" in p for p in problems)
    assert any("bad asset name" in p for p in problems)


@pytest.mark.parametrize("text, kind", [
    ("我的手机 13812345678", "phone"),
    ("发到 kid@example.com", "email"),
    ("身份证 110101200801011234", "cn_id"),
    ("id 3f505ae6-feb6-4e27-9d1a-84a90dfc1ed5", "uuid"),
    ("订单 123456789012", "long_number"),
    ("data:image/jpeg;base64,AAAA", "data_url"),
    ("ward/3f505ae6-feb6-4e27/companion/x.jpg", "storage_path"),
    ("看 https://example.com", "url"),
])
def test_identifiers_are_detected_in_any_text_field(text, kind):
    assert kind in dataset.pii_findings(_case(student_said=text))
    assert kind in dataset.pii_findings(_case(history=[{"author": "ward", "text": text}]))
    assert kind in dataset.pii_findings(_case(note=text))


def test_scrub_removes_what_validate_would_reject():
    text = "我是小明，电话 13812345678，邮箱 a@b.cn，号码 123456789012"
    cleaned = dataset.scrub(text, names=("小明",))
    assert "小明" not in cleaned
    assert dataset.pii_findings(_case(student_said=cleaned)) == []


def test_clock_times_and_short_numbers_are_not_identifiers():
    assert dataset.pii_findings(_case(student_said="kling beach 13:00 和 Return to Bali at 16:30")) == []


def test_history_longer_than_the_production_window_is_rejected():
    rows = [{"author": "ward", "text": "x"}] * 8
    assert dataset.validate([_case(history=rows)]) == []
    with pytest.raises(ValueError):
        _case(history=rows + [{"author": "ward", "text": "y"}])


def test_dataset_hash_is_stable_and_tracks_content():
    base = [_case(), _case(id="turn-test-01", turn_index=1)]
    assert dataset.dataset_hash(base) == dataset.dataset_hash(list(reversed(base)))
    changed = [_case(), _case(id="turn-test-01", turn_index=1, student_said="换一句")]
    assert dataset.dataset_hash(base) != dataset.dataset_hash(changed)


def test_intent_cases_cannot_assert_tutoring_fields():
    with pytest.raises(ValueError):
        _case(component="companion.intent", expect={"outcome_in": ["pronounce"]})
    with pytest.raises(ValueError):
        _case(expect={"intent_in": ["tutoring"]})


def test_validate_command_succeeds_on_the_committed_dataset(capsys):
    assert main(["validate"]) == 0
    assert "cases" in capsys.readouterr().out
