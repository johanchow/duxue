from app.contexts.study.domain.start_cue import SceneRead, StartCueError, StartCuePolicy, fallback_text


def test_no_other_session_offers_start_and_one_snooze():
    decision = StartCuePolicy.decide(
        other_session=False,
        scene=SceneRead("settling_in"),
        snooze_count=0,
        past_end=False,
    )
    assert decision.disposition == "present"
    assert decision.actions == ("start_due_task", "snooze_once")
    assert decision.primary_action == "start_due_task"


def test_another_session_offers_continue_or_switch():
    decision = StartCuePolicy.decide(
        other_session=True,
        scene=SceneRead("already_working"),
        snooze_count=0,
        past_end=False,
    )
    assert decision.actions[0] == "continue_current"
    assert "pause_current_and_start_due" in decision.actions
    assert "start_due_task" not in decision.actions


def test_away_holds_without_a_sentence():
    decision = StartCuePolicy.decide(
        other_session=False,
        scene=SceneRead("away"),
        snooze_count=0,
        past_end=False,
    )
    assert decision.disposition == "hold"
    assert decision.actions == ()


def test_missing_frames_are_no_observation_and_cannot_claim_the_desk():
    scene = SceneRead("no_observation", "no_frames")
    decision = StartCuePolicy.decide(other_session=False, scene=scene, snooze_count=0, past_end=False)
    assert decision.scene_claim_allowed is False
    text = fallback_text(
        due_title="数学",
        start_label="19:00",
        planned_minutes=40,
        other_title=None,
        earlier_titles=[],
        scene=scene,
    )
    assert "没看到书桌" in text
    assert "已经在写" not in text


def test_second_snooze_is_not_offered():
    decision = StartCuePolicy.decide(
        other_session=False,
        scene=SceneRead("other_activity"),
        snooze_count=1,
        past_end=False,
    )
    assert "snooze_once" not in decision.actions


def test_past_end_expires_before_a_card():
    decision = StartCuePolicy.decide(
        other_session=True,
        scene=SceneRead("away"),
        snooze_count=0,
        past_end=True,
    )
    assert decision.disposition == "expire"


def test_earlier_unstarted_tasks_share_one_sentence():
    text = fallback_text(
        due_title="英语",
        start_label="19:40",
        planned_minutes=20,
        other_title=None,
        earlier_titles=["数学"],
        scene=SceneRead("settling_in"),
    )
    assert text.startswith("数学也还没开始")
    assert "英语" in text


def test_no_observation_requires_a_gap_reason():
    try:
        SceneRead("no_observation")
    except StartCueError as error:
        assert error.code == "missing_gap_reason"
    else:
        raise AssertionError("expected missing_gap_reason")
