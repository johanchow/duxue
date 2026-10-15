import copy

import pytest

from app.application.workflows.tutor_turn import TutorTurnCandidate
from app.application.workflows.tutor_visual import describe
from tests.support.fakes import tutor_raw

STEPS = {
    "kind": "steps", "alt": "水循环分四步",
    "steps": [{"label": "蒸发"}, {"label": "凝结", "detail": "水汽变成小水珠"}, {"label": "降水"}],
}
COMPARE = {
    "kind": "compare", "alt": "植物细胞和动物细胞的区别",
    "columns": [
        {"title": "植物细胞", "items": ["有细胞壁", "有叶绿体"]},
        {"title": "动物细胞", "items": ["没有细胞壁", "没有叶绿体"]},
    ],
    "row_labels": ["外层", "能量"],
}
SEGMENT = {
    "kind": "segment", "alt": "小明有 3 份，小红有 5 份，合计未知",
    "bars": [
        {"label": "小明", "segments": [{"value": 3}]},
        {"label": "小红", "segments": [{"value": 5}]},
    ],
    "brackets": [{"bar": 1, "label": "合计", "unknown": True}],
}
NUMBER_LINE = {
    "kind": "number_line", "alt": "数轴上标出了 -2 和 3", "min": -5, "max": 5, "step": 1,
    "marks": [{"label": "A", "at": -2}, {"label": "区间", "start": 0, "end": 3, "end_closed": False}],
}
SVG = {
    "kind": "svg",
    "alt": "直角三角形两直角边为 3 和 4，斜边未知",
    "title": "直角三角形",
    "svg": (
        '<svg viewBox="0 0 680 180" width="100%" role="img">'
        '<title>直角三角形</title>'
        '<polygon points="220,140 220,40 380,140" fill="#E6F1FB" stroke="#185FA5" stroke-width="1.5"/>'
        '<text x="200" y="95" font-size="13" fill="#0C447C">3</text>'
        '<text x="300" y="160" font-size="13" fill="#0C447C">4</text>'
        '<text x="315" y="82" font-size="13" fill="#A32D2D">?</text>'
        '</svg>'
    ),
}


def cand(visual, act="guide", **extra):
    return TutorTurnCandidate.model_validate(tutor_raw(act, visual=visual, **extra))


@pytest.mark.parametrize("visual", [STEPS, COMPARE, SEGMENT, NUMBER_LINE, SVG], ids=lambda v: v["kind"])
def test_each_supported_kind_is_kept_and_described(visual):
    candidate = cand(visual, act="answer", relation="none")
    assert candidate.visual is not None and candidate.visual_dropped is None
    assert candidate.visual.kind == visual["kind"]
    text = describe(candidate.visual)
    assert visual["alt"] in text


@pytest.mark.parametrize("act", ["chat", "clarify", "redirect", "safety", "pronounce"])
def test_a_visual_on_an_act_without_body_is_dropped_not_rejected(act):
    raw = tutor_raw(act, relation=None, visual=STEPS)
    candidate = TutorTurnCandidate.model_validate(raw)
    assert candidate.visual is None
    assert candidate.visual_dropped == "visual_not_applicable"


def test_blank_visual_is_absent_not_a_drop():
    for blank in ("", {}, None, []):
        candidate = cand(blank)
        assert candidate.visual is None and candidate.visual_dropped is None


def test_model_cannot_report_its_own_drop_reason_or_set_a_kind_outside_the_vocabulary():
    candidate = TutorTurnCandidate.model_validate(tutor_raw(visual=None, visual_dropped="x"))
    assert candidate.visual_dropped is None
    unknown_kind = cand({"kind": "geometry", "alt": "三角形", "points": []})
    assert unknown_kind.visual is None and unknown_kind.visual_dropped == "visual_invalid"
    assert cand("<svg/>").visual_dropped == "visual_invalid"


def mutated(base, mutate):
    visual = copy.deepcopy(base)
    mutate(visual)
    return visual


@pytest.mark.parametrize("bad", [
    mutated(STEPS, lambda v: v.update(steps=v["steps"][:1])),                                  # < 2
    mutated(STEPS, lambda v: v.update(steps=[{"label": f"步{i}"} for i in range(6)])),          # > 5
    mutated(STEPS, lambda v: v.update(alt="")),                                                # alt required
    mutated(STEPS, lambda v: v["steps"][0].update(label="x" * 121)),                           # too long (> 120)
    mutated(STEPS, lambda v: v["steps"][0].update(label="看 https://a.cn")),                    # url
    mutated(STEPS, lambda v: v["steps"][0].update(label="**蒸发**x<br>")),                      # html
    mutated(STEPS, lambda v: v["steps"][0].update(label="$x^2$")),                             # latex
    mutated(COMPARE, lambda v: v["columns"][0].update(items=["只有一行"])),                      # misaligned
    mutated(COMPARE, lambda v: v.update(row_labels=["只有一个"])),                               # row_labels mismatch
    mutated(COMPARE, lambda v: v.update(columns=v["columns"][:1])),                            # < 2 columns
    mutated(SEGMENT, lambda v: v["brackets"][0].update(bar=5)),                                # no such bar
    mutated(SEGMENT, lambda v: v.update(bars=v["bars"] * 3)),                                  # > 4 bars
    mutated(NUMBER_LINE, lambda v: v.update(min=5, max=-5)),                                   # range
    mutated(NUMBER_LINE, lambda v: v.update(step=0.1)),                                        # > 20 ticks
    mutated(NUMBER_LINE, lambda v: v["marks"][0].update(at=99)),                               # outside
    mutated(NUMBER_LINE, lambda v: v["marks"][0].update(start=1, end=2)),                      # point and interval
    mutated(NUMBER_LINE, lambda v: v["marks"][1].update(start=3, end=0)),                      # inverted
    mutated(NUMBER_LINE, lambda v: v.update(marks=[{"at": i} for i in range(9)])),             # > 8
    mutated(SVG, lambda v: v.update(svg="<!DOCTYPE svg>" + v["svg"])),                         # doctype
    mutated(SVG, lambda v: v.update(svg="<html>" + v["svg"] + "</html>")),                     # html wrapper
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("0 0 680 180", "0 0 500 180"))),      # non-680 width
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("0 0 680 180", "0 0 680 20"))),       # height < 40
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("0 0 680 180", "0 0 680 2000"))),     # height > 1600
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("</svg>", "<script>alert(1)</script></svg>"))),
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("</svg>", "<foreignObject/></svg>"))),
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("<polygon ", '<polygon onclick="x()" '))),
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("font-size=\"13\"", "font-size=\"9\""))),
    mutated(SVG, lambda v: v.update(svg=v["svg"].replace("#E6F1FB", "url(https://evil.test/x)"))),
    mutated(SVG, lambda v: v.update(svg='<svg viewBox="0 0 680 120"><title>空图</title></svg>')),  # no shapes
])
def test_invalid_or_over_budget_visuals_are_dropped_whole(bad):
    candidate = cand(bad)
    assert candidate.visual is None
    assert candidate.visual_dropped == "visual_invalid"
    assert candidate.content  # the words are untouched


@pytest.mark.parametrize("bad", [
    mutated(SEGMENT, lambda v: v["bars"][0]["segments"].append({"unknown": True, "value": 7})),
    mutated(SEGMENT, lambda v: v["bars"][0]["segments"].append({"unknown": True, "label": "共 12 个"})),
    mutated(SEGMENT, lambda v: v["brackets"][0].update(value=8)),
    mutated(SEGMENT, lambda v: v["brackets"][0].update(label="合计8")),
    mutated(NUMBER_LINE, lambda v: v["marks"].append({"label": "x", "unknown": True, "at": 2})),
    mutated(NUMBER_LINE, lambda v: v["marks"].append({"label": "x=2", "unknown": True})),
])
def test_an_unknown_quantity_must_not_carry_a_number(bad):
    candidate = cand(bad)
    assert candidate.visual is None
    assert candidate.visual_dropped == "visual_unknown_value"


def test_unknown_marks_have_no_position_and_are_described_as_unknown():
    visual = mutated(NUMBER_LINE, lambda v: v["marks"].append({"label": "x", "unknown": True}))
    text = describe(cand(visual).visual)
    assert "标记 x：位置未知" in text
    segment = describe(cand(SEGMENT).visual)
    assert "括号（线段 小红）：合计未知" in segment


def test_svg_normalizes_connector_fill_and_viewbox_height_and_extracts_texts():
    raw_svg = (
        '<svg viewBox="0 0 680 100">'
        '<defs><marker id="arrow" viewBox="0 0 10 10"><path d="M2 1L8 5L2 9" stroke="#333"/></marker></defs>'
        '<rect x="40" y="40" width="160" height="80" fill="#E6F1FB"/>'
        '<path d="M200 80L280 80" stroke="#888780" marker-end="url(#arrow)"/>'
        '<polyline points="280,80 340,80" stroke="#888780"/>'
        '<text x="120" y="80" font-size="13">直角边 <tspan>3</tspan></text>'
        '<text x="300" y="80" font-size="13">斜边 ?</text>'
        '</svg>'
    )
    candidate = cand({"kind": "svg", "alt": "直角边与斜边", "svg": raw_svg})
    assert candidate.visual is not None and candidate.visual_dropped is None
    normalized = candidate.visual.svg
    # rect y=40, height=80 -> max_bottom=120 -> H auto-expanded from 100 to 140
    assert 'viewBox="0 0 680 140"' in normalized
    assert 'width="100%"' in normalized
    assert 'role="img"' in normalized
    assert normalized.count('fill="none"') >= 3
    desc = describe(candidate.visual)
    assert "图内文字：直角边 3 | 斜边 ?" in desc


def test_bilingual_compare_titles_and_svg_with_xml_comments_are_kept():
    compare_with_en = {
        "kind": "compare",
        "alt": "对比光的反射和折射原理",
        "columns": [
            {"title": "反射 (Reflection)", "items": ["光碰到物体表面弹回", "入射角等于反射角", "例子：照镜子、水面倒影"]},
            {"title": "折射 (Refraction)", "items": ["光进入另一种介质发生偏折", "传播速度改变导致方向变化", "例子：筷子在水里变弯、透镜成像"]},
        ],
        "row_labels": ["现象", "原理", "生活实例"],
    }
    svg_with_comments = {
        "kind": "svg",
        "alt": "光的反射和折射原理示意图",
        "title": "光的反射与折射",
        "svg": (
            '<svg viewBox="0 0 680 300" width="100%" role="img">'
            '<!-- Background -->'
            '<rect x="0" y="0" width="680" height="300" fill="#F9FAFB"/>'
            '<!-- Interface Line -->'
            '<line x1="40" y1="150" x2="640" y2="150" stroke="#9CA3AF" stroke-width="2"/>'
            '<text x="180" y="50" font-size="14" fill="#0C447C">反射 (Reflection)</text>'
            '</svg>'
        ),
    }
    c1 = cand(compare_with_en, act="answer", relation="none")
    c2 = cand(svg_with_comments, act="answer", relation="none")
    assert c1.visual is not None and c1.visual_dropped is None
    assert c2.visual is not None and c2.visual_dropped is None
    assert "<!--" not in c2.visual.svg


def test_svg_with_unescaped_inequality_in_text_is_kept():
    refraction_svg = {
        "kind": "svg",
        "alt": "光从空气斜射入水中的折射过程示意图（折射角 r < 入射角 i）",
        "title": "光的折射过程",
        "svg": (
            '<svg viewBox="0 0 680 300" width="100%" role="img">'
            '<!-- Air and Water Backgrounds -->'
            '<rect x="0" y="0" width="680" height="150" fill="#F9FAFB"/>'
            '<rect x="0" y="150" width="680" height="150" fill="#E6F1FB"/>'
            '<line x1="0" y1="150" x2="680" y2="150" stroke="#3B82F6" stroke-width="2"/>'
            '<text x="500" y="250" font-size="14" fill="#0C447C">折射角 r < 入射角 i</text>'
            '</svg>'
        ),
    }
    c = cand(refraction_svg, act="answer", relation="none")
    assert c.visual is not None and c.visual_dropped is None
    assert "折射角 r < 入射角 i" in describe(c.visual)


def test_every_json_example_in_the_tutor_prompt_is_a_valid_candidate():
    """提示词里的示例是模型照抄的样板，必须通过契约，且图示例必须真的保留图。"""
    import json

    from app.infrastructure.ai.prompts import PROMPTS

    text = PROMPTS["tutoring.turn.system.v12"].text
    decoder, found, start = json.JSONDecoder(), [], 0
    while (index := text.find("例如 {", start)) != -1:
        example, end = decoder.raw_decode(text, index + 3)
        found.append(example)
        start = end
    assert any("visual" in example for example in found)
    assert any(example.get("visual", {}).get("kind") == "svg" for example in found)
    for example in found:
        candidate = TutorTurnCandidate.model_validate(example)
        assert candidate.visual_dropped is None
        assert ("visual" in example) == (candidate.visual is not None)


def test_the_prompt_offers_exactly_the_kinds_the_contract_accepts():
    from app.infrastructure.ai.prompts import PROMPTS

    text = PROMPTS["tutoring.turn.system.v12"].text
    for kind in ("steps", "compare", "segment", "number_line", "svg"):
        assert f'"kind":"{kind}"' in text
    for later in ("geometry", "layers"):
        assert f'"kind":"{later}' not in text
