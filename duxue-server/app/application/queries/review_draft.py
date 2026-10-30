"""Produce editable candidate aspects from a Ward's own expression."""

from __future__ import annotations

from fastapi import HTTPException

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.runtime import execute_workflow
from app.application.commands.self_reviews import DIMENSIONS
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError


def propose_review_aspects(raw_expression: str) -> list[dict]:
    raw = raw_expression.strip()
    if not raw or len(raw) > 4000:
        raise HTTPException(422, "summary must contain 1 to 4000 characters")
    try:
        catalog = load_catalog()
        state = execute_workflow(
            catalog.spec("review-aspects"),
            handlers={"evaluation.review-aspects": lambda _state: components.invoke_agent_component(
                spec=catalog.component("review-aspects", "run"),
                user=build_context("evaluation.review-aspects", raw_expression=raw),
            )},
        )
        candidate = state["results"]["review-aspects.run"].unwrap()
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
