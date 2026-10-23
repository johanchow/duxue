"""Produce editable candidate aspects from a Ward's own expression."""

from __future__ import annotations

import json

from fastapi import HTTPException

from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError
from app.application.commands.self_reviews import DIMENSIONS


def propose_review_aspects(raw_expression: str) -> list[dict]:
    raw = raw_expression.strip()
    if not raw or len(raw) > 4000:
        raise HTTPException(422, "summary must contain 1 to 4000 characters")
    try:
        candidate = components.invoke_json_component(
            spec=components.COMPONENTS.get("evaluation.review-aspects"),
            user=json.dumps({"raw_expression": raw}, ensure_ascii=False),
        )
    except ModelGatewayError:
        return []
    rows = candidate.get("aspects") if isinstance(candidate, dict) else None
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        dimension = row.get("dimension")
        statement = row.get("statement")
        quote = row.get("source_quote")
        if (dimension in DIMENSIONS and isinstance(statement, str)
                and 0 < len(statement.strip()) <= 300 and isinstance(quote, str)
                and quote.strip() and quote.strip() in raw):
            result.append({
                "dimension": dimension, "statement": statement.strip(),
                "source_quote": quote.strip(),
            })
    return result
