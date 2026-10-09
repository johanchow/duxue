"""对话窗口里的图片以视觉内容进入每条模型调用，而不是一个 had_image 标记。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.application.ports.companion import RunInvocation
from app.application.queries.run_transcript import (
    current_turn_images,
    select_recent_utterances,
    visible_utterances,
)
from app.application.workflows.tutoring_workflow import TutoringWorkflow
from app.infrastructure.ai.model_gateway import AgentTextCandidate
from app.infrastructure.ai.utterance_window import instruction_with_window, user_content
from app.infrastructure.persistence.models import (
    CompanionCommand,
    CompanionMessage,
    ConversationThread,
    uid,
)
from tests.support.fakes import StaticTutorModel
from tests.support.factories import create_ward

PIXELS = "data:image/jpeg;base64,YQ=="


def _row(author: str, text: str, refs: list[str] | None = None) -> dict:
    return {"turn_id": uid(), "author": author, "text": text, "attachment_refs": refs or []}


def test_window_rows_carry_authorized_pixels_and_no_flag_or_path():
    own, foreign = "ward/w1/companion/a.jpg", "ward/w2/companion/b.jpg"
    rows, _ = select_recent_utterances(
        [_row("ward", "这张图是什么意思", [own, foreign]), _row("companion", "哪一行？")],
        exclude_turn_id=None,
    )
    views = visible_utterances(rows, ward_id="w1", read_image=lambda key: f"data:{key}")
    assert views[0]["image_urls"] == [f"data:{own}"]
    assert "image_urls" not in views[1]
    for view in views:
        assert "had_image" not in view
        assert "attachment_refs" not in view


def test_picture_only_utterance_stays_in_the_window():
    rows, omitted = select_recent_utterances(
        [_row("ward", "", ["ward/w1/companion/a.jpg"]), _row("ward", "这是什么")], exclude_turn_id=None,
    )
    assert omitted == 0 and len(rows) == 2
    views = visible_utterances(rows, ward_id="w1", read_image=lambda key: PIXELS)
    assert views[0] == {"author": "ward", "text": "", "image_urls": [PIXELS]}


def test_unreadable_picture_is_reported_not_guessed_and_strict_fails():
    rows = [_row("ward", "看图", ["ward/w1/companion/a.jpg"])]

    def broken(key: str) -> str:
        raise OSError("gone")

    assert visible_utterances(rows, ward_id="w1", read_image=broken)[0]["image_urls"] == [None]
    content = user_content({"content": "它呢"}, visible_utterances(rows, ward_id="w1", read_image=broken))
    assert content[1]["text"] == "图片1：无法读取。"
    try:
        visible_utterances(rows, ward_id="w1", read_image=broken, strict=True)
    except OSError:
        pass
    else:
        raise AssertionError("strict window must fail on an unreadable picture")


def test_only_the_newest_pictures_fit_the_budget():
    rows = [_row("ward", f"第{i}张", [f"ward/w1/companion/{i}.jpg"]) for i in range(4)]
    views = visible_utterances(rows, ward_id="w1", read_image=lambda key: key, image_budget=2)
    assert [view.get("image_urls") for view in views] == [
        None, None, ["ward/w1/companion/2.jpg"], ["ward/w1/companion/3.jpg"],
    ]


def test_user_content_numbers_window_and_current_pictures_in_one_message():
    window = [
        {"author": "ward", "text": "第一张", "image_urls": ["data:a", "data:b"]},
        {"author": "companion", "text": "好的"},
    ]
    parts = user_content({"content": "这张呢"}, window, ["data:c"])
    payload = json.loads(parts[0]["text"])
    assert payload["recent_utterances"][0]["image_ids"] == [1, 2]
    assert "image_ids" not in payload["recent_utterances"][1]
    assert payload["current_image_ids"] == [3]
    assert "had_image" not in parts[0]["text"]
    assert "data:" not in parts[0]["text"]
    assert [p["image_url"]["url"] for p in parts if p["type"] == "image_url"] == ["data:a", "data:b", "data:c"]
    assert [p["text"] for p in parts[1:] if p["type"] == "text"] == ["图片1：", "图片2：", "图片3："]


def test_instruction_text_never_embeds_pixels():
    text = instruction_with_window("说明", [{"author": "ward", "text": "看", "image_urls": [PIXELS]}], 1)
    assert PIXELS not in text
    assert '"image_ids": [1]' in text
    assert "current_image_ids=[2]" in text


def test_tutoring_sends_window_and_current_pictures_to_every_model_call(db, monkeypatch):
    ward = create_ward(db)
    thread = ConversationThread(ward_id=ward.id)
    db.add(thread)
    db.flush()
    command = CompanionCommand(id=uid(), ward_id=ward.id, thread_id=thread.id, payload_digest="prior")
    db.add(command)
    db.flush()
    old_key = f"ward/{ward.id}/companion/old.jpg"
    new_key = f"ward/{ward.id}/companion/new.jpg"
    db.add(CompanionMessage(
        ward_id=ward.id, thread_id=thread.id, command_id=command.id, turn_id=uid(), attempt=1,
        thread_version=1, author_type="ward", content="这是第一页", attachment_refs=[old_key],
    ))
    db.commit()
    monkeypatch.setattr(
        "app.application.queries.run_transcript._default_reader", lambda key: f"data:image/jpeg;base64,{key[-7:-4]}",
    )
    model = StaticTutorModel()
    TutoringWorkflow(db, turn_model=model).invoke(RunInvocation(
        run_id=uid(), thread_id=thread.id, ward_id=ward.id, agent_type="tutoring",
        turn={"content": "这一页第三题怎么做", "tutoring_directive": "ask", "attachment_keys": [new_key]},
    ))
    call = model.calls[0]
    assert call["recent_utterances"][0]["image_urls"] == ["data:image/jpeg;base64,old"]
    assert call["current_images"] == ["data:image/jpeg;base64,new"]
    assert "had_image" not in call["instruction"] and "base64" not in call["instruction"]


def test_other_wards_current_pictures_are_not_read():
    assert current_turn_images("w1", ["ward/w2/companion/x.jpg"], read_image=lambda key: PIXELS) == []
    assert current_turn_images("w1", ["ward/w1/companion/x.jpg"], read_image=lambda key: PIXELS) == [PIXELS]


def test_tutor_turn_gateway_attaches_window_and_current_pictures(monkeypatch):
    from app.infrastructure.ai import tutor_turn_model

    sent: dict = {}

    def chat(**kwargs):
        sent.update(kwargs)
        return {"act": "hint"}

    monkeypatch.setattr(tutor_turn_model, "_chat", chat)
    tutor_turn_model.QwenTutorTurnGateway().complete(
        envelope={}, instruction="{}",
        recent_utterances=[{"author": "ward", "text": "第一页", "image_urls": ["data:a"]}],
        current_images=["data:b"],
    )
    assert [p["image_url"]["url"] for p in sent["user"] if p["type"] == "image_url"] == ["data:a", "data:b"]
