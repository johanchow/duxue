from datetime import datetime, timedelta, timezone

import pytest

from app.contexts.behavior_analysis.domain.observation import (
    Cell,
    EvidenceFrame,
    Manifest,
    ObservationAssembler,
    ObservationWindow,
    validate_outcome,
)

T = datetime(2026, 11, 12, 11, tzinfo=timezone.utc)


def manifest():
    return Manifest(
        "ward",
        "camera",
        1,
        T,
        T + timedelta(minutes=1),
        tuple(EvidenceFrame(str(i), T + timedelta(seconds=15 * i)) for i in range(4)),
    )


def outcome(activity="writing"):
    return [
        {
            "start": (T + timedelta(seconds=15 * i)).isoformat(),
            "end": (T + timedelta(seconds=15 * (i + 1))).isoformat(),
            "activity": activity,
            "evidence_frame_ids": [str(i)],
        }
        for i in range(4)
    ]


def test_outcome_requires_authorized_target_evidence():
    rows = outcome()
    rows[0]["evidence_frame_ids"] = ["foreign"]
    with pytest.raises(ValueError):
        validate_outcome(manifest(), rows)


def test_context_cannot_fill_target_missing_slot():
    m = manifest()
    m = Manifest(m.ward_id, m.camera_id, 1, m.start, m.end, m.frames[1:])
    rows = outcome()
    rows[0]["evidence_frame_ids"] = ["1"]
    with pytest.raises(ValueError):
        validate_outcome(m, rows)


def test_model_cannot_extend_observation_or_overlap():
    rows = outcome()
    rows[0]["end"] = (T + timedelta(seconds=30)).isoformat()
    with pytest.raises(ValueError):
        validate_outcome(manifest(), rows)


def test_missing_and_unknown_are_separate_and_conserve_time():
    m = manifest()
    m = Manifest(m.ward_id, m.camera_id, 1, m.start, m.end, m.frames[:2])
    cells = validate_outcome(m, outcome("unknown")[:2])
    result = ObservationAssembler().assemble(cells, [(T, T + timedelta(minutes=1))])
    assert result["totals"] == {"unknown": 30.0, "missing": 30.0}
    assert result["coverage"]["received_seconds"] == 30
    assert result["coverage"]["interpretable_seconds"] == 0


def test_missing_time_breaks_continuous_help_run():
    cells = [
        Cell(T, T + timedelta(minutes=2), "still_with_material", ("a",)),
        Cell(
            T + timedelta(minutes=3),
            T + timedelta(minutes=5),
            "still_with_material",
            ("b",),
        ),
    ]
    result = ObservationAssembler().assemble(cells, [(T, T + timedelta(minutes=5))])
    assert [
        r["seconds"] for r in result["runs"] if r["activity"] == "still_with_material"
    ] == [120, 120]


def test_duplicate_sources_cannot_double_count():
    cell = Cell(T, T + timedelta(seconds=15), "writing", ("a",))
    with pytest.raises(ValueError):
        ObservationAssembler().assemble([cell, cell], [(T, T + timedelta(minutes=1))])


def test_no_known_range_means_no_coverage_percentage():
    result = ObservationAssembler().assemble(
        validate_outcome(manifest(), outcome()), None
    )
    assert result["coverage"]["expected_seconds"] is None
    assert result["coverage"]["ratio"] is None


def test_reclaimed_attempt_cannot_commit_even_for_same_input():
    window = ObservationWindow("fingerprint")
    first = window.claim()
    second = window.claim()
    with pytest.raises(ValueError):
        window.accept(first, "fingerprint")
    window.accept(second, "fingerprint")
    assert window.status == "interpreted"


def test_changed_input_fences_old_model_result():
    window = ObservationWindow("first")
    attempt = window.claim()
    window.invalidate("second")
    with pytest.raises(ValueError):
        window.accept(attempt, "first")
    assert window.input_version == 2


def test_long_absence_splits_observed_episodes_without_inventing_completion():
    cells = [
        Cell(T, T + timedelta(minutes=1), "writing", ("a",)),
        Cell(T + timedelta(minutes=1), T + timedelta(minutes=6), "away", ("b",)),
        Cell(
            T + timedelta(minutes=6),
            T + timedelta(minutes=7),
            "reading_material",
            ("c",),
        ),
    ]
    result = ObservationAssembler().assemble(cells, None)
    assert len(result["episodes"]) == 2
    assert result["episodes"][0]["end"] == T + timedelta(minutes=1)
    assert result["totals"]["away"] == 300
