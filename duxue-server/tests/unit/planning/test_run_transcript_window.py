from app.application.queries.run_transcript import select_recent_utterances


def test_window_drops_the_current_turn_and_keeps_prior_originals():
    question = "已从图片中识别出行程安排：码头出发 7:00。请确认是否创建？"
    kept, omitted = select_recent_utterances([
        {"turn_id": "ask", "author": "ward", "text": "把图片里的安排成任务。", "had_image": True},
        {"turn_id": "ask", "author": "companion", "text": question, "had_image": False},
        {"turn_id": "confirm", "author": "ward", "text": "是的，都安排成任务。", "had_image": False},
    ], exclude_turn_id="confirm")

    assert omitted == 0
    assert [item["text"] for item in kept] == ["把图片里的安排成任务。", question]


def test_window_omits_oldest_utterances_without_rewriting_them():
    kept, omitted = select_recent_utterances([
        {"turn_id": "1", "author": "ward", "text": "旧的一句很长", "had_image": False},
        {"turn_id": "2", "author": "companion", "text": "码头出发", "had_image": False},
        {"turn_id": "3", "author": "ward", "text": "rumah pohon", "had_image": False},
    ], exclude_turn_id=None, max_messages=8, max_chars=15)

    assert omitted == 1
    assert [item["text"] for item in kept] == ["码头出发", "rumah pohon"]
    assert "旧的一句很长" not in "".join(item["text"] for item in kept)


def test_window_keeps_the_tail_of_one_oversized_utterance():
    kept, omitted = select_recent_utterances([
        {"turn_id": "1", "author": "companion", "text": "开头省略码头出发 7:00", "had_image": False},
    ], exclude_turn_id=None, max_chars=8)

    original = "开头省略码头出发 7:00"
    assert omitted == 0
    assert kept[0]["leading_omitted"] is True
    assert kept[0]["text"] == original[-8:]
    assert "开头省略" not in kept[0]["text"]
