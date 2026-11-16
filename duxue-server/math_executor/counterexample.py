"""Deterministic numerical counterexample search using high-precision mpmath.

Invariant:
- Finding a valid point inside the stated domain where an inequality/equation fails
  is a deterministic REFUTATION (`status="ok"`, `verdict="not_equal"`).
- Failing to find a counterexample NEVER proves universal truth (`status="unknown"`, `verdict="unknown"`).
"""

from __future__ import annotations

import ast
import json
import re
from itertools import product
from typing import Any

import mpmath as mp


def _grid_points(low: float, high: float, count: int) -> list[mp.mpf]:
    lo, hi = mp.mpf(str(low)), mp.mpf(str(high))
    if lo > hi:
        raise ValueError("invalid_bound_order")
    if lo == hi:
        return [lo]
    pts = [lo + (hi - lo) * mp.mpf(i) / mp.mpf(count - 1) for i in range(count)]
    # Add interior golden-ratio / algebraic probes such as 1, 0, 1/2, e, pi if inside [lo, hi]
    for special in (mp.mpf(0), mp.mpf(1), mp.mpf(-1), mp.mpf("0.5"), mp.e, mp.pi / 4, mp.pi / 2):
        if lo <= special <= hi:
            pts.append(special)
    # Deduplicate preserving order
    unique: list[mp.mpf] = []
    for pt in pts:
        if not any(abs(pt - existing) < mp.mpf("1e-18") for existing in unique):
            unique.append(pt)
    return unique


def search_counterexample_operation(s, p, args: dict[str, Any]) -> dict[str, Any]:
    raw_rel = args["relation"]
    raw_bounds = args["bounds"]
    if not isinstance(raw_rel, str) or not 0 < len(raw_rel) <= 512:
        raise ValueError("invalid_relation")
    if not isinstance(raw_bounds, dict) or not 1 <= len(raw_bounds) <= 3:
        raise ValueError("bounds_requires_1_to_3_variables")

    normalized = re.sub(r"(?<![<>!=])=(?!=)", "==", raw_rel)
    tree = ast.parse(normalized, mode="eval")
    if not isinstance(tree.body, ast.Compare) or len(tree.body.ops) != 1:
        raise ValueError("relation_must_be_single_comparison")

    left_expr = p._visit_expr(normalized, tree.body.left)
    right_expr = p._visit_expr(normalized, tree.body.comparators[0])
    op_node = tree.body.ops[0]

    free_syms = (left_expr.free_symbols | right_expr.free_symbols)
    var_names = sorted(str(sym) for sym in free_syms)
    if not set(var_names).issubset(set(raw_bounds)):
        raise ValueError("missing_bounds_for_free_symbols")

    ordered_syms = [p.variable(name) for name in var_names]
    per_dim = 17 if len(ordered_syms) == 1 else (11 if len(ordered_syms) == 2 else 6)
    grids = []
    for sym in ordered_syms:
        b = raw_bounds[str(sym)]
        if not isinstance(b, list) or len(b) != 2 or not all(isinstance(v, (int, float)) for v in b):
            raise ValueError("invalid_variable_bounds")
        if abs(b[0]) > 1e6 or abs(b[1]) > 1e6:
            raise ValueError("bound_magnitude_limit")
        grids.append(_grid_points(float(b[0]), float(b[1]), per_dim))

    fn_left = s.lambdify(ordered_syms, left_expr, modules="mpmath")
    fn_right = s.lambdify(ordered_syms, right_expr, modules="mpmath")
    guard_fns = [
        (kind, s.lambdify(ordered_syms, g_expr, modules="mpmath"))
        for kind, g_expr in p.domain_guards
    ]

    with mp.workdps(35):
        tol = mp.mpf("1e-12")
        strict_tol = mp.mpf("1e-10")
        for combo in product(*grids):
            # Verify domain guards at candidate point first
            valid_domain = True
            for kind, gfn in guard_fns:
                try:
                    gv = gfn(*combo)
                except Exception:  # noqa: BLE001
                    valid_domain = False
                    break
                if isinstance(gv, mp.mpc) or not mp.isfinite(gv):
                    valid_domain = False
                    break
                if kind == "!=" and abs(gv) <= tol:
                    valid_domain = False
                    break
                if kind == ">=" and gv < -tol:
                    valid_domain = False
                    break
                if kind == ">" and gv <= tol:
                    valid_domain = False
                    break
            if not valid_domain:
                continue

            try:
                lv = fn_left(*combo)
                rv = fn_right(*combo)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(lv, mp.mpc) or isinstance(rv, mp.mpc):
                if abs(mp.im(lv)) > tol or abs(mp.im(rv)) > tol:
                    continue
                lv, rv = mp.re(lv), mp.re(rv)
            if not (mp.isfinite(lv) and mp.isfinite(rv)):
                continue

            diff = lv - rv
            violated = False
            if isinstance(op_node, ast.LtE):
                violated = diff > strict_tol
            elif isinstance(op_node, ast.Lt):
                violated = diff >= strict_tol
            elif isinstance(op_node, ast.GtE):
                violated = diff < -strict_tol
            elif isinstance(op_node, ast.Gt):
                violated = diff <= -strict_tol
            elif isinstance(op_node, ast.Eq):
                violated = abs(diff) > strict_tol
            elif isinstance(op_node, ast.NotEq):
                violated = abs(diff) <= tol
            else:
                raise ValueError("unsupported_comparison")

            if violated:
                witness = {
                    "counterexample_found": True,
                    "point": {
                        str(sym): mp.nstr(val, 10) for sym, val in zip(ordered_syms, combo)
                    },
                    "left_value": mp.nstr(lv, 12),
                    "right_value": mp.nstr(rv, 12),
                }
                return {
                    "status": "ok",
                    "result": json.dumps(witness, ensure_ascii=False),
                    "conditions": [],
                    "checked_scope": "equivalence",
                    "verdict": "not_equal",
                }

    return {
        "status": "unknown",
        "result": json.dumps({"counterexample_found": False}, ensure_ascii=False),
        "conditions": ["numerical_sampling_cannot_prove_universal_truth"],
        "checked_scope": "equivalence",
        "verdict": "unknown",
    }
