"""Exact discrete probability distributions, linear regression, and 2x2 chi-square tests."""

from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from typing import Any

from math_executor.arithmetic import arithmetic_eval, format_fraction


def _to_fraction(item: Any) -> Fraction:
    if isinstance(item, int) and not isinstance(item, bool):
        if abs(item) > 10**12:
            raise ValueError("number_out_of_bounds")
        return Fraction(item)
    if isinstance(item, float):
        return arithmetic_eval(str(item))
    if isinstance(item, str):
        return arithmetic_eval(item.strip())
    raise ValueError("invalid_numeric_value")


def _approx_decimal(frac: Fraction, places: int = 4) -> str:
    val = Decimal(frac.numerator) / Decimal(frac.denominator)
    quant = Decimal(10) ** (-places)
    return str(val.quantize(quant, rounding=ROUND_HALF_UP))


def probability_stats_operation(args: dict[str, Any]) -> dict[str, Any]:
    mode = args.get("mode")
    if mode == "discrete_distribution":
        raw_vals = args.get("values")
        raw_probs = args.get("probabilities")
        if (
            not isinstance(raw_vals, list)
            or not isinstance(raw_probs, list)
            or not 1 <= len(raw_vals) <= 50
            or len(raw_vals) != len(raw_probs)
        ):
            raise ValueError("invalid_distribution_inputs")
        vals = [_to_fraction(v) for v in raw_vals]
        probs = [_to_fraction(pr) for pr in raw_probs]
        prob_sum = sum(probs, Fraction(0))
        non_negative = all(pr >= 0 for pr in probs)
        valid = non_negative and prob_sum == Fraction(1)
        payload: dict[str, Any] = {
            "valid_distribution": valid,
            "probability_sum": format_fraction(prob_sum),
            "all_nonnegative": non_negative,
        }
        if valid:
            exp_x = sum((x * pr for x, pr in zip(vals, probs)), Fraction(0))
            exp_x2 = sum((x * x * pr for x, pr in zip(vals, probs)), Fraction(0))
            var_x = exp_x2 - exp_x * exp_x
            payload["expectation"] = format_fraction(exp_x)
            payload["variance"] = format_fraction(var_x)
            payload["expectation_approx"] = _approx_decimal(exp_x, 4)
            payload["variance_approx"] = _approx_decimal(var_x, 4)
        return {
            "engine_version": "prob-stats-v1",
            "status": "ok",
            "result": json.dumps(payload, ensure_ascii=False),
            "conditions": [],
            "checked_scope": "value",
        }

    if mode == "linear_regression":
        raw_x = args.get("x")
        raw_y = args.get("y")
        if (
            not isinstance(raw_x, list)
            or not isinstance(raw_y, list)
            or not 2 <= len(raw_x) <= 100
            or len(raw_x) != len(raw_y)
        ):
            raise ValueError("invalid_regression_inputs")
        xs = [_to_fraction(v) for v in raw_x]
        ys = [_to_fraction(v) for v in raw_y]
        n = Fraction(len(xs))
        x_bar = sum(xs, Fraction(0)) / n
        y_bar = sum(ys, Fraction(0)) / n
        s_xx = sum(((x - x_bar) ** 2 for x in xs), Fraction(0))
        if s_xx == 0:
            raise ValueError("degenerate_regression_x")
        s_xy = sum(((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys)), Fraction(0))
        s_yy = sum(((y - y_bar) ** 2 for y in ys), Fraction(0))
        slope = s_xy / s_xx
        intercept = y_bar - slope * x_bar
        r_squared = (s_xy * s_xy) / (s_xx * s_yy) if s_yy != 0 else Fraction(1)
        payload = {
            "x_mean": format_fraction(x_bar),
            "y_mean": format_fraction(y_bar),
            "slope": format_fraction(slope),
            "intercept": format_fraction(intercept),
            "r_squared": format_fraction(r_squared),
            "slope_approx": _approx_decimal(slope, 4),
            "intercept_approx": _approx_decimal(intercept, 4),
        }
        return {
            "engine_version": "prob-stats-v1",
            "status": "ok",
            "result": json.dumps(payload, ensure_ascii=False),
            "conditions": [],
            "checked_scope": "value",
        }

    if mode == "chi2_2x2":
        table = args.get("table")
        if (
            not isinstance(table, list)
            or len(table) != 2
            or not all(isinstance(row, list) and len(row) == 2 for row in table)
        ):
            raise ValueError("invalid_2x2_table")
        a, b = _to_fraction(table[0][0]), _to_fraction(table[0][1])
        c, d = _to_fraction(table[1][0]), _to_fraction(table[1][1])
        if any(v < 0 or v.denominator != 1 for v in (a, b, c, d)):
            raise ValueError("contingency_counts_must_be_nonnegative_integers")
        n = a + b + c + d
        denom = (a + b) * (c + d) * (a + c) * (b + d)
        if n <= 0 or denom == 0:
            raise ValueError("degenerate_contingency_table")
        chi2 = n * (a * d - b * c) ** 2 / denom
        payload = {
            "n": format_fraction(n),
            "chi2_exact": format_fraction(chi2),
            "chi2_approx": _approx_decimal(chi2, 3),
            "exceeds_2_706": chi2 > Fraction(2706, 1000),
            "exceeds_3_841": chi2 > Fraction(3841, 1000),
            "exceeds_6_635": chi2 > Fraction(6635, 1000),
            "exceeds_10_828": chi2 > Fraction(10828, 1000),
        }
        return {
            "engine_version": "prob-stats-v1",
            "status": "ok",
            "result": json.dumps(payload, ensure_ascii=False),
            "conditions": [],
            "checked_scope": "value",
        }

    raise ValueError("invalid_probability_stats_mode")
