from app.api.schemas import CompanionTurnRequest
from app.application.workflows.image_target import (
    choose_image_target,
    keep_target_images,
)
from app.application.workflows.tutoring_workflow import TutoringWorkflow


def _window():
    return [
        {"author": "ward", "text": "第一张", "image_urls": ["data:old"]},
        {"author": "companion", "text": "第4题单位要换算"},
    ]


def test_readable_new_image_never_calls_selector_and_drops_old_pixels():
    window = _window()
    target = choose_image_target(
        window, ["data:new"], select=lambda _: (_ for _ in ()).throw(AssertionError("selector called")),
    )
    rows, images = keep_target_images(window, ["data:new"], target)
    assert target.ids == (2,)
    assert "image_urls" not in rows[0]
    assert rows[1]["text"] == "第4题单位要换算"
    assert images == ["data:new"]
    assert TutoringWorkflow._judge_images(rows, images) == ["data:new"]


def test_all_current_images_are_selected_without_model():
    target = choose_image_target(_window(), ["data:new1", "data:new2"])
    assert target.ids == (2, 3)
    rows, images = keep_target_images(_window(), ["data:new1", "data:new2"], target)
    assert "image_urls" not in rows[0]
    assert images == ["data:new1", "data:new2"]


def test_explicit_comparison_keeps_only_nearest_old_picture():
    request = CompanionTurnRequest(content="和上一张比较", tutoring_intent="compare_previous_image")
    assert request.tutoring_intent == "compare_previous_image"
    window = [
        {"author": "ward", "text": "第一页", "image_urls": ["data:older"]},
        {"author": "ward", "text": "第二页", "image_urls": ["data:latest"]},
    ]
    target = choose_image_target(window, ["data:new"], compare_previous=True)
    rows, images = keep_target_images(window, ["data:new"], target)
    assert target.ids == (2, 3)
    assert "image_urls" not in rows[0]
    assert rows[1]["image_urls"] == ["data:latest"]
    assert images == ["data:new"]


def test_one_old_picture_is_used_without_selector():
    assert choose_image_target(_window(), []).ids == (1,)


def test_multiple_old_pictures_use_selector_and_can_skip_all_for_text_question():
    window = _window() + [{"author": "ward", "text": "第二张", "image_urls": ["data:other"]}]
    target = choose_image_target(
        window, [], select=lambda _: {"target_image_ids": [], "ambiguous": False},
    )
    rows, images = keep_target_images(window, [], target)
    assert not target.ambiguous and not target.ids
    assert not images and all("image_urls" not in row for row in rows)


def test_ambiguous_unreadable_or_invalid_old_selection_asks_for_clarification():
    window = _window() + [{"author": "ward", "text": "第二张", "image_urls": ["data:other"]}]
    for result in (
        {"target_image_ids": [], "ambiguous": True},
        {"target_image_ids": [3], "ambiguous": False},
        {"target_image_ids": [True], "ambiguous": False},
    ):
        target = choose_image_target(window, [], select=lambda _rows, result=result: result)
        assert target.ambiguous and not target.ids
    assert choose_image_target([], [None]).ambiguous
