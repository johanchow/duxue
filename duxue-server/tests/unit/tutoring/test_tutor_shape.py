from app.application.workflows.tutor_shape import MAX_CHARS, lint_shape


def test_a_well_shaped_guide_has_no_flags():
    assert lint_shape("guide", "你已经找到了总数。那每份有几个呢？") == []


def test_too_long_uses_the_act_limit():
    assert lint_shape("chat", "好" * (MAX_CHARS["chat"] + 1)) == ["too_long"]
    long_answer = "好" * (MAX_CHARS["answer"] - 5)
    assert lint_shape("answer", long_answer) == []
    assert "too_long" in lint_shape("answer", long_answer + "你还想知道什么呢？")
    assert lint_shape("safety", "好" * 5000) == []  # no limit for acts not in the table


def test_guide_with_two_questions_is_flagged_but_answer_may_ask_one():
    assert lint_shape("guide", "已知什么？要求什么？") == ["multi_question"]
    assert lint_shape("guide", "先想想已知条件。你能说出来吗？") == []
    assert "multi_question" not in lint_shape("answer", "这是 in advance。你还有别的问题吗？")


def test_list_heavy_needs_three_items_and_half_of_the_lines():
    items = "\n".join(f"- 第{i}点" for i in range(3))
    assert lint_shape("answer", items) == ["list_heavy"]
    assert lint_shape("answer", f"总的来说有三点。\n{items}\n先看第一点。\n再看第二点。\n最后。") == []


def test_unpaired_dollar_ignores_escaped_dollars_and_paired_math():
    assert lint_shape("answer", "算式是 $x+1") == ["unpaired_dollar"]
    assert lint_shape("answer", "算式是 $x+1$。") == []
    assert lint_shape("answer", r"这个本子 \$5 一本。") == []


def test_raw_html_is_flagged_but_comparison_signs_are_not():
    assert lint_shape("answer", "换行用 <br> 不好") == ["raw_html"]
    assert lint_shape("answer", "因为 3 < 5，所以左边小。") == []
