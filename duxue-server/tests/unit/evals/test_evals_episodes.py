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
    assert len([row for row in rows if row.review_batch != "image-review-v1"]) == 4
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


def test_scope_switch_uses_actual_history_and_keeps_old_problem_for_return():
    import json

    from evals.conversations import load_conversations

    episode = next(row for row in episodes.load_episodes() if row.id == "knowledge-switch-and-return")
    replay = next(row for row in load_conversations() if row.id == "protection-scope-conversation")
    model = StaticTutorModel(
        tutor_raw(content="第一轮提示"), tutor_raw(content="第二轮提示"),
        replay.attempts[0].candidate,
        tutor_raw(content="返回原题的提示"), tutor_raw(content="下一步提示"),
        tutor_raw(content="核验学生提交的结果"),
    )

    class Judge(StaticLeakJudge):
        def leaks(self, **kwargs):
            super().leaks(**kwargs)
            return {"leaks": False, "reason": "none", "answer_protected": self.calls != 3}

        def visual_leaks(self, **kwargs):
            return False

    judge = Judge()
    result = run_episode(episode, Backends(tutor_model=model, leak_judge=judge))
    assert result.passed and len(result.steps) == 6
    assert [step.observation.answer_protected for step in result.steps] == [True, True, False, True, True, True]
    assert result.steps[2].observation.visual_kind == "compare"
    assert {"author": "companion", "text": replay.attempts[0].candidate["content"]} in model.calls[3]["recent_utterances"]
    contexts = [json.loads(value) for value in judge.problems]
    assert contexts[2]["recent_problems"] == contexts[3]["recent_problems"] == episode.turns[0].context.recent_problems
    assert contexts[3]["current_request"] == episode.turns[3].student_said


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


def test_multimodal_episode_keeps_actual_generated_reply_and_image_identity(tmp_path):
    from app.agent_specs.image_refs import image_ref
    from evals.runner import read_asset
    row = _episode().model_dump(mode='json')
    name = 'img-aaaaaaaaaaaa.jpg'
    (tmp_path / name).write_bytes(b'image')
    row['turns'][0]['images'] = [name]
    model = StaticTutorModel(tutor_raw(content='第一张图的实际生成回复'))
    selection_windows = []

    def select(window, content):
        selection_windows.append(window)
        return {'target_image_ids': [1], 'ambiguous': False}

    result = run_episode(episodes.Episode.model_validate(row),
                         Backends(tutor_model=model, leak_judge=StaticLeakJudge(False),
                                  image_target_selector=select), assets_dir=tmp_path)
    assert result.passed
    assert result.steps[1].observation.selected_images == [name]
    assert model.calls[1]['recent_utterances'][0]['image_urls']
    assert selection_windows[0][1]['text'] == '第一张图的实际生成回复'
    assert selection_windows[0][1]['image_target_refs'] == [image_ref(read_asset(tmp_path / name))]
    assert not any(row['author'] == 'companion' for row in model.calls[1]['recent_utterances'])
