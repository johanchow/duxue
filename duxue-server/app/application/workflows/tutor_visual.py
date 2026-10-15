"""tutor-turn.v4 的可选配图 `visual`：关闭词汇表、结构校验与文字化。

模型只表达"有哪些对象、什么关系或数量"，不给坐标、样式或任何可执行内容；布局与绘制由客户端完成。
设计与取舍见 docs/technical/domain-tutoring-presentation.md §五。

结构非法、超预算或违反不变量时，调用方丢弃**整张图**，不截断、不猜测修复。
本模块只做结构与确定性不变量；"图是否泄露作业答案"由出口检查的图判官负责。
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal
from xml.etree import ElementTree

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
_BAD_TEXT = re.compile(r"[`$\\\n\r]|https?:|www\.|\]\(|!\[|<\s*/?[a-zA-Z][a-zA-Z0-9]*\b[^>]*>|^\s*#")
_BOUND = 1_000_000


def _plain(value: str) -> str:
    if _BAD_TEXT.search(value):
        raise ValueError("visual text must be plain text")
    return value


def _text(limit: int):
    return Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=limit), AfterValidator(_plain),
    ]


Text = _text(120)
ShortText = _text(120)
Detail = _text(120)
Number = Annotated[float, Field(ge=-_BOUND, le=_BOUND, allow_inf_nan=False)]


def _has_digit(*texts: str | None) -> bool:
    return any(ch.isdigit() for text in texts for ch in (text or ""))


def _unknown_has_no_value(unknown: bool, *, numbers: tuple, texts: tuple) -> None:
    """`unknown=true` 的量不得带数值，也不得在文字里写出数字：挡住"图上直接标出答案"。"""
    if unknown and (any(n is not None for n in numbers) or _has_digit(*texts)):
        raise ValueError("unknown_value: an unknown quantity must not carry a number")


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: _text(120) | None = None
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


# ---- 受限矢量图（flutter_svg 渲染） --------------------------------------------------------
SVG_CANVAS_WIDTH = 680
SVG_MIN_HEIGHT = 40
SVG_MAX_HEIGHT = 1600
SVG_MIN_FONT_SIZE = 11.0
SVG_MAX_CHARS = 16_000
SVG_MAX_ELEMENTS = 120
SVG_MAX_SHAPES = 80
_SVG_NS = "http://www.w3.org/2000/svg"
ElementTree.register_namespace("", _SVG_NS)

_SVG_ALLOWED_TAGS = frozenset({
    "svg", "defs", "marker", "g", "rect", "circle", "ellipse", "line",
    "polyline", "polygon", "path", "text", "tspan", "title", "desc",
    "linearGradient", "stop",
})
_SVG_SHAPE_TAGS = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"})
_SVG_XML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_SVG_TEXT_BODY = re.compile(r"(<(?:text|tspan|title|desc)\b[^>]*>)([\s\S]*?)(</(?:text|tspan|title|desc)>)", re.I)
_SVG_RAW_AMP = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
_SVG_FORBIDDEN_RAW = re.compile(
    r"<!(?:DOCTYPE|ENTITY)|<\?xml|<(?:/?\s*(?:html|head|body|script|style|foreignObject|iframe|form|image|a)\b)"
    r"|/\*|position\s*:\s*fixed|\b(?:localStorage|sessionStorage|javascript:|data:)\b|https?:|www\.",
    re.I,
)
_SVG_URL_REF = re.compile(r"url\(([^)]*)\)", re.I)
_SVG_SAFE_FRAGMENT = re.compile(r"^['\"]?#[A-Za-z_][A-Za-z0-9_.-]*['\"]?$")
_SVG_FONT_SIZE_CSS = re.compile(r"font-size\s*:\s*([0-9.]+)\s*(px|pt|em|rem)?", re.I)
_SVG_NUM_UNIT = re.compile(r"^\s*([0-9.]+)\s*(px|pt|em|rem)?\s*$", re.I)


def _strip_svg_ns(name: str) -> str:
    if name.startswith("{"):
        ns, _, local = name[1:].partition("}")
        if ns != _SVG_NS:
            raise ValueError(f"unsupported svg namespace: {ns}")
        return local
    if ":" in name:
        raise ValueError(f"unsupported prefixed svg name: {name}")
    return name


def _check_font_size(raw: str, unit: str | None) -> None:
    unit_norm = (unit or "px").lower()
    if unit_norm in ("em", "rem"):
        raise ValueError("relative font-size units are not allowed in svg")
    size = float(raw)
    px = size if unit_norm == "px" else size * 4.0 / 3.0
    if px < SVG_MIN_FONT_SIZE:
        raise ValueError(f"svg font-size {size}{unit_norm} is below {SVG_MIN_FONT_SIZE}px")


def _escape_svg_text_nodes(code: str) -> str:
    """模型常在 `<text>` 内直接写 `r < i` 或 `A & B`，未转义会导致 XML 解析失败；仅对文本节点内容转义 `<`/`>`/`&`。"""
    def _fix(match: re.Match[str]) -> str:
        open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
        if "<tspan" in body.lower():
            return match.group(0)
        escaped = _SVG_RAW_AMP.sub("&amp;", body).replace("<", "&lt;").replace(">", "&gt;")
        return f"{open_tag}{escaped}{close_tag}"

    return _SVG_TEXT_BODY.sub(_fix, code)


def _validate_and_normalize_svg(raw_svg: str) -> str:
    code = _escape_svg_text_nodes(_SVG_XML_COMMENT.sub("", raw_svg).strip())
    if len(code) > SVG_MAX_CHARS:
        raise ValueError("svg exceeds maximum character budget")
    if _SVG_FORBIDDEN_RAW.search(code):
        raise ValueError("svg contains forbidden markup or patterns")
    if not code.lower().startswith("<svg") or not code.lower().endswith("</svg>"):
        raise ValueError("svg must be a single <svg>...</svg> fragment")
    if len(re.findall(r"<svg[\s>]", code, flags=re.I)) != 1:
        raise ValueError("svg must contain exactly one <svg> element")

    try:
        root = ElementTree.fromstring(code)
    except ElementTree.ParseError as exc:
        raise ValueError(f"invalid svg xml: {exc}") from exc

    if _strip_svg_ns(root.tag) != "svg":
        raise ValueError("root element must be <svg>")

    vb_raw = root.get("viewBox")
    if not vb_raw:
        raise ValueError("svg root requires viewBox='0 0 680 H'")
    vb_parts = vb_raw.split()
    if len(vb_parts) != 4:
        raise ValueError("svg viewBox must have 4 numbers: '0 0 680 H'")
    try:
        x0, y0, w, h = (float(p) for p in vb_parts)
    except ValueError as exc:
        raise ValueError("svg viewBox values must be numbers") from exc
    if abs(x0) > 0.01 or abs(y0) > 0.01 or abs(w - SVG_CANVAS_WIDTH) > 0.01:
        raise ValueError("svg viewBox must start with '0 0 680'")
    if h < SVG_MIN_HEIGHT or h > SVG_MAX_HEIGHT:
        raise ValueError(f"svg viewBox height must be between {SVG_MIN_HEIGHT} and {SVG_MAX_HEIGHT}")

    element_count = 0
    shape_count = 0
    max_bottom = 0.0

    for el in root.iter():
        element_count += 1
        if element_count > SVG_MAX_ELEMENTS:
            raise ValueError("svg exceeds maximum element budget")
        tag = _strip_svg_ns(el.tag)
        if tag not in _SVG_ALLOWED_TAGS:
            raise ValueError(f"unsupported svg tag: {tag}")
        if tag in _SVG_SHAPE_TAGS:
            shape_count += 1
            if shape_count > SVG_MAX_SHAPES:
                raise ValueError("svg exceeds maximum shape budget")

        for attr_key, attr_val in list(el.attrib.items()):
            k = _strip_svg_ns(attr_key)
            k_low = k.lower()
            if k_low.startswith("on") or k_low in {"href", "src"}:
                raise ValueError(f"forbidden svg attribute: {k}")
            if _SVG_FORBIDDEN_RAW.search(attr_val):
                raise ValueError(f"forbidden value in svg attribute {k}")
            for match in _SVG_URL_REF.finditer(attr_val):
                target = match.group(1).strip()
                if not _SVG_SAFE_FRAGMENT.match(target):
                    raise ValueError("svg url() may only reference internal #id fragments")
            if k_low == "font-size":
                m = _SVG_NUM_UNIT.match(attr_val)
                if not m:
                    raise ValueError("invalid svg font-size attribute")
                _check_font_size(m.group(1), m.group(2))
            elif k_low == "style":
                for m in _SVG_FONT_SIZE_CSS.finditer(attr_val):
                    _check_font_size(m.group(1), m.group(2))

        # 几何底边估算（防底部被裁切与越界）
        try:
            if tag == "rect":
                ry = float(el.get("y", 0))
                rh = float(el.get("height", 0))
                max_bottom = max(max_bottom, ry + rh)
            elif tag in ("circle", "ellipse"):
                cy = float(el.get("cy", 0))
                r = float(el.get("ry", el.get("r", 0)))
                max_bottom = max(max_bottom, cy + r)
            elif tag == "line":
                max_bottom = max(max_bottom, float(el.get("y1", 0)), float(el.get("y2", 0)))
            elif tag == "text":
                max_bottom = max(max_bottom, float(el.get("y", 0)) + 8.0)
        except ValueError:
            pass

        # 连接器规范化：path / polyline 作连接线时确保 fill="none"
        if tag == "polyline":
            if el.get("fill") is None:
                el.set("fill", "none")
        elif tag == "path":
            has_marker = bool(el.get("marker-end") or el.get("marker-start"))
            fill = el.get("fill")
            if has_marker:
                if fill is None:
                    el.set("fill", "none")
                elif fill.strip().lower() != "none":
                    raise ValueError("svg connector path with marker must have fill='none'")
            elif fill is None and el.get("stroke") is not None:
                el.set("fill", "none")

    if shape_count < 1:
        raise ValueError("svg must contain at least one shape element")
    if max_bottom + 20.0 > SVG_MAX_HEIGHT:
        raise ValueError("svg content exceeds maximum height")

    effective_h = max(int(math.ceil(h)), int(math.ceil(max_bottom + 20.0)))
    root.set("viewBox", f"0 0 {SVG_CANVAS_WIDTH} {effective_h}")
    root.set("width", "100%")
    if root.get("role") is None:
        root.set("role", "img")
    return ElementTree.tostring(root, encoding="unicode")


def extract_svg_texts(raw_svg: str) -> list[str]:
    """按文档顺序提取 SVG 内 `<title>`、`<desc>`、`<text>`（含嵌套 `<tspan>`）的可见文本。"""
    try:
        root = ElementTree.fromstring(_escape_svg_text_nodes(_SVG_XML_COMMENT.sub("", raw_svg).strip()))
    except ElementTree.ParseError:
        return []
    texts: list[str] = []
    for el in root.iter():
        tag = _strip_svg_ns(el.tag)
        if tag in ("title", "desc", "text"):
            chunk = " ".join("".join(el.itertext()).split())
            if chunk and (not texts or texts[-1] != chunk):
                texts.append(chunk)
    return texts


class SvgVisual(_Base):
    """受限静态矢量图：680 基准宽，本地确定性清洗与校验，客户端用 flutter_svg 渲染。"""

    kind: Literal["svg"]
    svg: str = Field(min_length=20, max_length=SVG_MAX_CHARS)

    @model_validator(mode="after")
    def _validate_svg(self):
        self.svg = _validate_and_normalize_svg(self.svg)
        for chunk in extract_svg_texts(self.svg):
            if _SVG_FORBIDDEN_RAW.search(chunk):
                raise ValueError("svg text contains forbidden content")
        return self


Visual = Annotated[
    StepsVisual | CompareVisual | SegmentVisual | NumberLineVisual | SvgVisual,
    Field(discriminator="kind"),
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
    elif isinstance(visual, SvgVisual):
        texts = extract_svg_texts(visual.svg)
        if texts:
            lines.append("图内文字：" + " | ".join(texts))
    return "\n".join(lines)
