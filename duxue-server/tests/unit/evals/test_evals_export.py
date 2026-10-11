from uuid import uuid4

import pytest

from app.application.process_managers.companion_coordinator import _CLARIFY_REPLY
from app.application.workflows.tutor_turn import FALLBACK_TEXT, REMINDER
from app.infrastructure.persistence.models import CompanionMessage
from evals import dataset, export


def _rows(*items):
    return [{"turn_id": f"t{i}", "author": a, "text": t, "attachment_refs": refs}
            for i, (a, t, refs) in enumerate(items)]


def _build(rows, component="tutoring.turn", names=()):
    return export.build_cases(rows, conversation_id="abc12345", component=component,
                              asset_for=lambda key: f"img-{key.rsplit('/', 1)[-1][:4]}.jpg", names=names)


def test_one_decision_point_per_ward_turn_with_the_window_before_it():
    rows = _rows(("ward", "鞋用英语怎么说？", []), ("companion", "shoe", []), ("ward", "怎么读？", []))
    cases = _build(rows)
    assert [c.id for c in cases] == ["turn-abc12345-00", "turn-abc12345-01"]
    assert cases[0].history == [] and cases[1].student_said == "怎么读？"
    assert [(h.author, h.text) for h in cases[1].history] == [("ward", "鞋用英语怎么说？"), ("companion", "shoe")]
    assert all(c.label_status == "proposed" and c.source == "real" for c in cases)
    assert dataset.validate(cases) == []


def test_window_is_capped_like_production():
    rows = _rows(*[("ward" if i % 2 == 0 else "companion", f"句子{i}", []) for i in range(21)], ("ward", "最后一句", []))
    last = _build(rows)[-1]
    assert len(last.history) == 8 and last.history[-1].text == "句子20"


def test_images_become_asset_names_in_history_and_current_turn():
    rows = _rows(("ward", "看图", ["ward/x/companion/aaaa1111.jpg"]), ("companion", "好", []),
                 ("ward", "这个怎么读？", ["ward/x/companion/bbbb2222.jpg"]))
    cases = _build(rows)
    assert cases[0].images == ["img-aaaa.jpg"]
    assert cases[1].history[0].images == ["img-aaaa.jpg"] and cases[1].images == ["img-bbbb.jpg"]


def test_flags_mark_the_failure_modes_seen_in_the_incidents():
    listed = "你问的是哪个？\n1. shoe\n2. 这个单词"
    rows = _rows(
        ("ward", "告诉我怎么发音？", []), ("companion", FALLBACK_TEXT, []),
        ("ward", "这个单词怎么读？", []), ("companion", listed, []),
        ("ward", "这个单词怎么读？", []), ("companion", listed, []),
        ("ward", "为什么会有打雷？", []), ("companion", _CLARIFY_REPLY, []),
        ("ward", "嗯", []),
    )
    flags = [c.flags for c in _build(rows)]
    assert flags[0] == ["fallback_reply"]
    assert flags[1] == ["clarify_reply"]
    assert flags[2] == ["clarify_reply", "clarify_repeat", "ward_repeat"]
    assert flags[3] == ["intent_unclear"]
    assert flags[4] == ["no_reply"]


def test_task_is_inferred_from_the_reminder_and_only_for_tutoring_cases():
    rows = _rows(("ward", "鞋用英语怎么说？", []), ("companion", f"shoe\n{REMINDER}", []))
    assert _build(rows)[0].context.task_active is True
    assert _build(rows, component="companion.intent")[0].context.task_active is False
    assert _build(rows, component="companion.intent")[0].id.startswith("intent-")


def test_identifiers_are_scrubbed_before_a_case_exists():
    rows = _rows(("ward", "我是小明，我的号码 13812345678", []), ("companion", "小明你好 a@b.cn", []), ("ward", "好的", []))
    cases = _build(rows, names=("小明",))
    assert "小明" not in cases[0].student_said and "13812345678" not in cases[0].student_said
    assert "小明" not in cases[1].history[1].text and "a@b.cn" not in cases[1].history[1].text
    assert dataset.validate(cases) == []


def test_a_picture_with_no_words_is_not_a_case():
    assert _build(_rows(("ward", "", ["ward/x/companion/aaaa1111.jpg"]), ("companion", "看到了", []))) == []


def test_asset_writer_stores_images_under_a_content_hash(tmp_path):
    asset_for = export.asset_writer(lambda key: b"same-bytes", tmp_path)
    first, second = asset_for("ward/x/companion/a.jpg"), asset_for("ward/y/companion/b.JPG")
    assert first == second and first.startswith("img-") and first.endswith(".jpg")
    assert (tmp_path / first).read_bytes() == b"same-bytes"
    assert "ward/" not in first


def test_load_thread_rows_reads_one_thread_in_order(db):
    def add(version, author, text, thread="abcdef12-0000-4000-8000-000000000001"):
        db.add(CompanionMessage(
            ward_id=str(uuid4()), thread_id=thread, command_id=str(uuid4()), thread_version=version,
            author_type=author, content=text, attachment_refs=[], turn_id=str(uuid4()),
        ))

    add(2, "companion", "shoe")
    add(1, "ward", "鞋用英语怎么说？")
    add(1, "ward", "别的线程", thread="ffffffff-0000-4000-8000-000000000002")
    db.flush()
    conversation_id, rows = export.load_thread_rows(db, "abcdef12")
    assert conversation_id == "abcdef12"
    assert [(r["author"], r["text"]) for r in rows] == [("ward", "鞋用英语怎么说？"), ("companion", "shoe")]
    with pytest.raises(ValueError, match="matches 0 threads"):
        export.load_thread_rows(db, "zzzz")
