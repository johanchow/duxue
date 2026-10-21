"""tutor-turn.v4 的只读工具。全部限于当前 Ward，不改变许可，没有副作用。

观察结果是不可信输入，只带类型化的状态：unique、ambiguous、no_match、tool_error。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.application.workflows.teaching_skills import history_candidates
from app.infrastructure.persistence.models import TutoringMessage, TutoringProblem

MAX_TOOL_CALLS = 3
MAX_MODEL_CALLS = 4
TOOL_NAMES = ("get_task_context", "get_attempt_summary", "lookup_history", "widget_guidelines")
_HISTORY_LIMIT = 3

SVG_WIDGET_GUIDELINES = """# SVG Visualizer Design System

Draw textbook-grade educational diagrams (教科书级的教学插图与原理示意图): accurate, well-proportioned, self-explanatory, and rich enough to make the concept immediately intuitive — never a crude stick-figure or bare single-shape sketch.

## 1. Canvas & Coordinate System
- `viewBox="0 0 680 H"` — width `680` is fixed and must never change; all coordinates are computed on this 680-wide canvas. Set `width="100%"` and `role="img"` on root `<svg>`.
- `H` = bottommost element y + 20 (between 40 and 1600). Do not guess H; compute it from your lowest element.
- Safe area: `x = 40..640`, `y = 40..(H-40)`. Keep all shapes and labels inside the safe area.
- Allowed tags only: `svg`, `defs`, `marker`, `g`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`, `path`, `text`, `tspan`, `title`, `desc`.
- No `<style>`, `<script>`, `<foreignObject>`, `<image>`, HTML tags, `<!-- comments -->`, gradients, shadows, or emoji.
- No rotated text.
- Every connector `<path>` or `<polyline>` MUST have `fill="none"`.
- Arrow marker for `<defs>`:
  `<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>`

## 2. Typography & Box Sizing
- Font sizes: title 14px (`font-weight="500"`), body/label 13px (`400`), caption/secondary 12px (`400`). Never below 11px; never use weight 600/700/bold.
- Every `<text>` inside a box or aligned to a point needs `dominant-baseline="central"` and explicit `text-anchor` (`start` | `middle` | `end`).
- Box width formula: `rect_width = max(title_chars * 14, subtitle_chars * 12) + 24` for Chinese text (or `chars * 7 + 24` for ASCII). Single-line box height = `44`, two-line box height = `56`.
- Minimum spacing: `60px` between nodes, `24px` padding inside containers, `12px` between text and shape edges.

## 3. Color Palette (Explicit Hex + Theme Variables)
- Neutral text & lines: `var(--color-text-primary)` (main text), `var(--color-text-secondary)` (labels/captions), `var(--color-border-tertiary)` (subtle guide lines).
- Always set an explicit `fill` on every shape (50/100 stop for fill, 600 stop for stroke, 800 stop for text inside):
  - Blue: fill `#E6F1FB` (or `#B5D4F4`), stroke `#185FA5`, text `#0C447C`
  - Amber: fill `#FAEEDA` (or `#FAC775`), stroke `#854F0B`, text `#633806`
  - Coral/Red: fill `#FAECE7`, stroke `#D85A30` (or `#A32D2D`), text `#712B13`
  - Teal: fill `#E1F5EE`, stroke `#0F6E56`, text `#085041`
  - Purple: fill `#EEEDFE`, stroke `#534AB7`, text `#3C3489`
  - Gray: fill `#F1EFE8`, stroke `#5F5E5A`, text `#444441`
- Complexity budget: at most 2-3 color ramps per diagram.

## 4. Diagram Guidance
- **Illustrative diagram**: draw textbook-grade simplified cross-sections, cutaways, or spatial models that clearly show the underlying mechanism, reference lines, angles/vectors, and causal relationships. Place labels outside the drawn object with thin leader lines so text never collides with shapes.
- **Structural diagram**: outermost container `rx="20"` with 50-level fill; inner regions `rx="10"` with 100-level fill; `>= 20px` padding; max 2-3 nesting levels.
- **Flowchart**: max 4-5 nodes per diagram; up to 4 boxes per horizontal row (`x = 40 + i * (w + 60)`).
- **Aligned grid & spatial notation** (二维对位演算式、竖式、配平/结构框架): align columns on a fixed x-grid (e.g. `40..48px` per column with `text-anchor="middle"` and `dominant-baseline="central"`), draw clear operator symbols and horizontal divider lines (`<line>`), and mark every uncomputed digit, coefficient, or unknown result slot with a highlighted dashed box and `?` (never fill in the solved answer on protected homework).
- **Chinese long division / 除法竖式**: draw the textbook `厂`-shaped division bracket as ONE connected left vertical and top horizontal stroke. Put the divisor to the left, dividend below the top bar to the right, and unknown quotient `?` above the top bar. Example frame only: `<path d="M250 140 L250 80 Q250 70 260 70 H375" fill="none" stroke="var(--color-text-primary)" stroke-width="2"/><text x="180" y="112">130</text><text x="300" y="112">660</text><text x="300" y="55">?</text>`. The operands here only illustrate placement; use the child's actual operands. Do not use `)` as the bracket, put the long horizontal below the dividend, or fill an uncomputed quotient digit. Omit subtraction rows until the child works out that step."""


class TutorToolbox:
    def __init__(
        self, db: Session, *, tutoring_session_id: str | None, problem: TutoringProblem | None,
        task_title: str | None, task_active: bool, window: list[dict],
    ):
        self.db = db
        self.tutoring_session_id = tutoring_session_id
        self.problem = problem
        self.task_title = task_title
        self.task_active = task_active
        self.window = window

    def run(self, name: str, args: dict | None) -> dict:
        args = args if isinstance(args, dict) else {}
        handler = {
            "get_task_context": self._task_context,
            "get_attempt_summary": self._attempt_summary,
            "lookup_history": self._lookup_history,
            "widget_guidelines": self._widget_guidelines,
        }.get(name)
        if handler is None:
            return {"tool": name, "status": "tool_error", "detail": "unknown_tool"}
        try:
            return {"tool": name, **handler(args)}
        except Exception:  # noqa: BLE001 - tool failures are intentionally isolated per observation.
            return {"tool": name, "status": "tool_error"}

    def _task_context(self, _args: dict) -> dict:
        if not self.task_active or not self.task_title:
            return {"status": "no_match"}
        return {"status": "unique", "task_title": self.task_title}

    def _attempt_summary(self, _args: dict) -> dict:
        row = self.problem
        if row is None:
            return {"status": "no_match"}
        return {
            "status": "unique", "substantive_attempts": row.substantive_attempts,
            "hints_given": row.hints_given, "evidence_summary": row.evidence_summary,
            "active_subgoal": row.active_subgoal, "problem_summary": row.summary,
        }

    def _lookup_history(self, args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"status": "no_match"}
        hits = [
            {"ref": item["ref"], "author": item["author"], "text": item["text"]}
            for item in history_candidates(self.window) if query in item["text"]
        ]
        if self.tutoring_session_id:
            rows = (
                self.db.query(TutoringMessage)
                .filter(TutoringMessage.tutoring_session_id == self.tutoring_session_id,
                        TutoringMessage.role == "ward", TutoringMessage.content.contains(query))
                .order_by(TutoringMessage.created_at.desc()).limit(_HISTORY_LIMIT).all()
            )
            hits += [{"ref": f"m:{row.id}", "author": "ward", "text": row.content} for row in rows]
        hits = hits[:_HISTORY_LIMIT]
        if not hits:
            return {"status": "no_match"}
        return {"status": "unique" if len(hits) == 1 else "ambiguous", "matches": hits}

    def _widget_guidelines(self, _args: dict) -> dict:
        return {"status": "unique", "guidelines": SVG_WIDGET_GUIDELINES}

