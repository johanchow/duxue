"""Multi-turn replay retains the actual tutor answer and stops after divergence."""

from evals import episodes
from evals.episode_runner import EpisodeResult, run_episode, summarize_episodes
from evals.runner import Backends
from tests.support.fakes import StaticLeakJudge, StaticTutorModel, tutor_raw


def _episode(first_expect=None):
    step = {
        "student_said": "Help with 2x+3=11.",
        "context": {"problem": {"summary": "解 2x+3=11", "active_subgoal": "先看常数项"}},
        "expect": first_expect or {"outcome_in": ["hint_like"]},
    }
    turns = [step, *[
        {"student_said": f"My attempt {i} is to subtract three on both sides.",
         "student_on": {"clarify": "The equation is 2x+3=11. Please guide me."} if i == 1 else {},
         "context": step["context"], "expect": {"outcome_in": ["hint_like"]}}
        for i in range(1, 6)
    ]]
    return episodes.Episode.model_validate({
        "id": "episode-test-sequence", "title": "Test sequence", "inspired_by": "self",
        "turns": turns, "note": "Authored test scenario",
    })


def test_committed_episodes_are_six_turns_and_have_stable_hash():
    rows = episodes.load_episodes()
    assert len(rows) == 24
    assert all(len(row.turns) == 6 for row in rows)
    assert episodes.episodes_hash(rows) == episodes.episodes_hash(list(reversed(rows)))
    assert episodes.validate_episodes(rows) == []


def test_actual_tutor_reply_enters_next_window():
    model = StaticTutorModel(*[tutor_raw("guide", f"Tutor reply {i}") for i in range(6)])
    result = run_episode(_episode(), Backends(tutor_model=model, leak_judge=StaticLeakJudge(False)))
    assert result.passed
    assert len(model.calls) == 6
    assert {"author": "companion", "text": "Tutor reply 0"} in model.calls[1]["recent_utterances"]
    assert len(model.calls[-1]["recent_utterances"]) <= 8


def test_branch_uses_previous_outcome_and_failure_stops_episode():
    model = StaticTutorModel(tutor_raw("clarify", "Which equation?", relation=None,
                                     candidates=["2x+3=11"]), tutor_raw("guide", "Try both sides."))
    result = run_episode(
        _episode({"outcome_in": ["clarify", "hint_like"]}),
        Backends(tutor_model=model, leak_judge=StaticLeakJudge(False)),
    )
    assert result.passed
    assert result.student_said[1] == "The equation is 2x+3=11. Please guide me."
    bad = StaticTutorModel(tutor_raw("answer", "The answer is 4.", relation="same"))
    stopped = run_episode(_episode(), Backends(tutor_model=bad, leak_judge=StaticLeakJudge(False)))
    assert not stopped.passed
    assert stopped.stopped_at == 0
    assert len(bad.calls) <= 2  # production leak repair may retry the failed turn
    summary = summarize_episodes([EpisodeResult(_episode(), [result, stopped])])
    assert summary["episodes"] == 1
    assert summary["stable_pass"] == 0
    assert summary["any_pass"] == 1
    assert summary["by_status"]["proposed"]["any_pass"] == 1
