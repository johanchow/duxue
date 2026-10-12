"""tutor-turn.v2 的可选配图 `visual`：关闭词汇表、结构校验与文字化。

模型只表达"有哪些对象、什么关系或数量"，不给坐标、样式或任何可执行内容；布局与绘制由客户端完成。
设计与取舍见 docs/technical/domain-tutoring-presentation.md §五。

结构非法、超预算或违反不变量时，调用方丢弃**整张图**，不截断、不猜测修复。
本模块只做结构与确定性不变量；"图是否泄露作业答案"由出口检查的图判官负责。
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

# 纯文本：不含 URL、HTML、Markdown 与 LaTeX 标记，不换行。
_BAD_TEXT = re.compile(r"[`$\\\n\r]|https?:|www\.|\]\(|!\[|<\s*/?[a-zA-Z!]|^\s*#")
_BOUND = 1_000_000


def _plain(value: str) -> str:
    if _BAD_TEXT.search(value):
        raise ValueError("visual text must be plain text")
    return value


def _text(limit: int):
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=limit), AfterValidator(_plain),
    ]


Text = _text(24)
ShortText = _text(12)
Detail = _text(40)
Number = Annotated[float, Field(ge=-_BOUND, le=_BOUND, allow_inf_nan=False)]


def _has_digit(*texts: str | None) -> bool:
    return any(ch.isdigit() for text in texts for ch in (text or ""))


def _unknown_has_no_value(unknown: bool, *, numbers: tuple, texts: tuple) -> None:
    """`unknown=true` 的量不得带数值，也不得在文字里写出数字：挡住"图上直接标出答案"。"""
    if unknown and (any(n is not None for n in numbers) or _has_digit(*texts)):
        raise ValueError("unknown_value: an unknown quantity must not carry a number")


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: _text(20) | None = None
    alt: _text(120)


# ---- 通用概念图 --------------------------------------------------------------------------
class Step(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: Text
    detail: Detail | None = None


class StepsVisual(_Base):
    kind: Literal["steps"]
    steps: list[Step] = Field(min_length=2, max_length=5)


class CompareColumn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: ShortText
    items: list[Text] = Field(min_length=1, max_length=4)


class CompareVisual(_Base):
    kind: Literal["compare"]
    columns: list[CompareColumn] = Field(min_length=2, max_length=3)
    row_labels: list[ShortText] | None = Field(default=None, max_length=4)

    @model_validator(mode="after")
    def _aligned(self):
        sizes = {len(column.items) for column in self.columns}
        if len(sizes) != 1:
            raise ValueError("compare columns must have the same number of items")
        if self.row_labels is not None and len(self.row_labels) != sizes.pop():
            raise ValueError("row_labels must match the number of items")
        return self


# ---- 学科图 ------------------------------------------------------------------------------
class Segment(BaseModel):
    """线段图中的一段：已知量带 `value`（份数或数量），未知量标 `unknown` 且不带数值。"""

    model_config = ConfigDict(extra="ignore")
    label: ShortText | None = None
    value: Number | None = None
    unknown: bool = False

    @model_validator(mode="after")
    def _unknown(self):
        _unknown_has_no_value(self.unknown, numbers=(self.value,), texts=(self.label,))
        return self


class Bar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    label: ShortText
    segments: list[Segment] = Field(min_length=1, max_length=6)


class Bracket(BaseModel):
    """括住一条线段，表示合计或差。`bar` 是 `bars` 的下标。"""

    model_config = ConfigDict(extra="ignore")
    bar: int = Field(ge=0)
    label: ShortText | None = None
    value: Number | None = None
    unknown: bool = False

    @model_validator(mode="after")
    def _unknown(self):
        _unknown_has_no_value(self.unknown, numbers=(self.value,), texts=(self.label,))
        return self


class SegmentVisual(_Base):
    kind: Literal["segment"]
    bars: list[Bar] = Field(min_length=1, max_length=4)
    brackets: list[Bracket] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def _brackets_point_at_bars(self):
        if any(bracket.bar >= len(self.bars) for bracket in self.brackets):
            raise ValueError("bracket refers to a bar that does not exist")
        return self


class Mark(BaseModel):
    """数轴上的标记：点（`at`）或区间（`start`、`end`）。未知标记没有位置，只在图旁说明。"""

    model_config = ConfigDict(extra="ignore")
    label: ShortText | None = None
    at: Number | None = None
    start: Number | None = None
    end: Number | None = None
    start_closed: bool = True
    end_closed: bool = True
    unknown: bool = False

    @model_validator(mode="after")
    def _shape(self):
        _unknown_has_no_value(self.unknown, numbers=(self.at, self.start, self.end), texts=(self.label,))
        if self.unknown:
            return self
        is_point = self.at is not None
        is_interval = self.start is not None and self.end is not None
        if is_point == is_interval or (is_point and (self.start is not None or self.end is not None)):
            raise ValueError("a mark is either a point or an interval")
        if is_interval and self.start >= self.end:
            raise ValueError("interval start must be below end")
        return self


class NumberLineVisual(_Base):
    kind: Literal["number_line"]
    min: Number
    max: Number
    step: Number
    marks: list[Mark] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _range(self):
        if not self.max > self.min or not self.step > 0 or (self.max - self.min) / self.step > 20:
            raise ValueError("number_line needs min < max, step > 0 and at most 20 intervals")
        for mark in self.marks:
            if mark.unknown:
                continue
            values = [v for v in (mark.at, mark.start, mark.end) if v is not None]
            if any(v < self.min or v > self.max for v in values):
                raise ValueError("mark lies outside the number line range")
        return self


Visual = Annotated[
    StepsVisual | CompareVisual | SegmentVisual | NumberLineVisual, Field(discriminator="kind"),
]
VISUAL_ADAPTER: TypeAdapter = TypeAdapter(Visual)

# 可承载图的正文：答案、辅导。其余 act 没有这样的正文，丢弃图是结构原因，不是教学判断。
VISUAL_ACTS = frozenset({"answer", "guide"})


def drop_reason(error: Exception) -> str:
    """校验失败的稳定归类，只含类别，不含内容。"""
    errors = getattr(error, "errors", None)
    if callable(errors) and any("unknown_value" in str(item.get("msg", "")) for item in errors()):
        return "visual_unknown_value"
    return "visual_invalid"


def _num(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else str(value)


def describe(visual) -> str:
    """把图转成一段文字：给泄露判官、答案标记兜底和独立输出安全审核。

    文字里保留所有可见字符和数值，以及 `unknown` 标记，让判官能看到"图上到底画了什么"。
    """
    lines = [f"图型：{visual.kind}"]
    if visual.title:
        lines.append(f"标题：{visual.title}")
    lines.append(f"说明：{visual.alt}")
    if isinstance(visual, StepsVisual):
        lines.append("步骤：" + " → ".join(
            step.label + (f"（{step.detail}）" if step.detail else "") for step in visual.steps
        ))
    elif isinstance(visual, CompareVisual):
        rows = visual.row_labels or [""] * len(visual.columns[0].items)
        for column in visual.columns:
            lines.append(f"{column.title}：" + "；".join(
                f"{row}{'：' if row else ''}{item}" for row, item in zip(rows, column.items)
            ))
    elif isinstance(visual, SegmentVisual):
        for bar in visual.bars:
            parts = [
                f"{seg.label or ''}{'未知' if seg.unknown else _num(seg.value)}" for seg in bar.segments
            ]
            lines.append(f"线段 {bar.label}：" + " | ".join(parts))
        for bracket in visual.brackets:
            amount = "未知" if bracket.unknown else _num(bracket.value)
            lines.append(f"括号（线段 {visual.bars[bracket.bar].label}）：{bracket.label or ''}{amount}")
    elif isinstance(visual, NumberLineVisual):
        lines.append(f"数轴：{_num(visual.min)} 到 {_num(visual.max)}，每格 {_num(visual.step)}")
        for mark in visual.marks:
            if mark.unknown:
                where = "位置未知"
            elif mark.at is not None:
                where = f"点 {_num(mark.at)}"
            else:
                left, right = ("[" if mark.start_closed else "("), ("]" if mark.end_closed else ")")
                where = f"区间 {left}{_num(mark.start)}, {_num(mark.end)}{right}"
            lines.append(f"标记 {mark.label or ''}：{where}")
    return "\n".join(lines)
