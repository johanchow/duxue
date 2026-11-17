"""7-base SI dimensional consistency verification for high-school physics formulas.

Base dimensions vector order: (M, L, T, I, Theta, N, J) over exact `fractions.Fraction`.
"""

from __future__ import annotations

import ast
import json
from fractions import Fraction
from typing import Any

DimVec = tuple[Fraction, Fraction, Fraction, Fraction, Fraction, Fraction, Fraction]
ZERO_DIM: DimVec = (Fraction(0),) * 7
BASE_UNITS: dict[str, DimVec] = {
    "1": ZERO_DIM,
    "M": (Fraction(1), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
    "L": (Fraction(0), Fraction(1), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
    "T": (Fraction(0), Fraction(0), Fraction(1), Fraction(0), Fraction(0), Fraction(0), Fraction(0)),
    "I": (Fraction(0), Fraction(0), Fraction(0), Fraction(1), Fraction(0), Fraction(0), Fraction(0)),
    "Theta": (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(1), Fraction(0), Fraction(0)),
    "N": (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(1), Fraction(0)),
    "J": (Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(0), Fraction(1)),
}
_DIMENSIONLESS_CONSTANTS = {"pi", "E"}
_TRANSCENDENTAL_FUNCS = {"sin", "cos", "tan", "cot", "asin", "acos", "atan", "exp", "ln", "log"}


class DimensionMismatch(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _add_vec(a: DimVec, b: DimVec) -> DimVec:
    return tuple(x + y for x, y in zip(a, b))  # type: ignore[return-value]


def _sub_vec(a: DimVec, b: DimVec) -> DimVec:
    return tuple(x - y for x, y in zip(a, b))  # type: ignore[return-value]


def _scale_vec(a: DimVec, k: Fraction) -> DimVec:
    return tuple(x * k for x in a)  # type: ignore[return-value]


def _format_dim(vec: DimVec) -> str:
    names = ("M", "L", "T", "I", "Theta", "N", "J")
    parts = []
    for name, power in zip(names, vec):
        if power == 0:
            continue
        if power == 1:
            parts.append(name)
        else:
            p_str = str(power.numerator) if power.denominator == 1 else f"({power.numerator}/{power.denominator})"
            parts.append(f"{name}**{p_str}")
    return " * ".join(parts) if parts else "1"


def _eval_scalar_exponent(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        frac = Fraction(str(node.value))
        if abs(frac) > 20 or frac.denominator > 20:
            raise ValueError("exponent_out_of_bounds")
        return frac
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        val = _eval_scalar_exponent(node.operand)
        return -val if isinstance(node.op, ast.USub) else val
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left = _eval_scalar_exponent(node.left)
        right = _eval_scalar_exponent(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise ValueError("division_by_zero")
        return left / right
    raise DimensionMismatch("non_constant_or_dimensional_exponent")


def _eval_dim_tree(node: ast.AST, env: dict[str, DimVec], *, depth: int = 0) -> DimVec:
    if depth > 24:
        raise ValueError("expression_too_deep")
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return ZERO_DIM
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _DIMENSIONLESS_CONSTANTS:
            return ZERO_DIM
        raise ValueError(f"undeclared_quantity:{node.id}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _eval_dim_tree(node.operand, env, depth=depth + 1)
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, (ast.Add, ast.Sub)):
            left = _eval_dim_tree(node.left, env, depth=depth + 1)
            right = _eval_dim_tree(node.right, env, depth=depth + 1)
            if left != right:
                raise DimensionMismatch(
                    f"additive_dimension_mismatch: {_format_dim(left)} vs {_format_dim(right)}"
                )
            return left
        if isinstance(node.op, ast.Mult):
            return _add_vec(
                _eval_dim_tree(node.left, env, depth=depth + 1),
                _eval_dim_tree(node.right, env, depth=depth + 1),
            )
        if isinstance(node.op, ast.Div):
            return _sub_vec(
                _eval_dim_tree(node.left, env, depth=depth + 1),
                _eval_dim_tree(node.right, env, depth=depth + 1),
            )
        if isinstance(node.op, ast.Pow):
            base_dim = _eval_dim_tree(node.left, env, depth=depth + 1)
            # Check if exponent contains physical quantities with non-zero dimension
            try:
                exp_dim = _eval_dim_tree(node.right, env, depth=depth + 1)
                if exp_dim != ZERO_DIM:
                    raise DimensionMismatch("dimensional_quantity_in_exponent")
            except ValueError:
                pass
            if base_dim == ZERO_DIM:
                return ZERO_DIM
            power = _eval_scalar_exponent(node.right)
            return _scale_vec(base_dim, power)
        raise ValueError("unsupported_operator")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        fn = node.func.id
        nargs = len(node.args)
        if fn == "sqrt" and nargs == 1:
            return _scale_vec(_eval_dim_tree(node.args[0], env, depth=depth + 1), Fraction(1, 2))
        if fn == "cbrt" and nargs == 1:
            return _scale_vec(_eval_dim_tree(node.args[0], env, depth=depth + 1), Fraction(1, 3))
        if fn == "abs" and nargs == 1:
            return _eval_dim_tree(node.args[0], env, depth=depth + 1)
        if fn in _TRANSCENDENTAL_FUNCS and nargs in (1, 2):
            for arg_node in node.args:
                arg_dim = _eval_dim_tree(arg_node, env, depth=depth + 1)
                if arg_dim != ZERO_DIM:
                    raise DimensionMismatch(
                        f"transcendental_argument_not_dimensionless: {fn}({_format_dim(arg_dim)})"
                    )
            return ZERO_DIM
        raise ValueError("unsupported_function")
    raise ValueError("unsupported_syntax")


def _parse_dim_spec(spec: str) -> DimVec:
    if not isinstance(spec, str) or not 0 < len(spec) <= 128:
        raise ValueError("invalid_dimension_spec")
    tree = ast.parse(spec, mode="eval")
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("dimension_spec_too_complex")
    return _eval_dim_tree(tree.body, BASE_UNITS)


def check_dimensions_operation(args: dict[str, Any]) -> dict[str, Any]:
    left_raw = args.get("left")
    right_raw = args.get("right")
    quantities_raw = args.get("quantities", {})
    if (
        not isinstance(left_raw, str)
        or not isinstance(right_raw, str)
        or not (0 < len(left_raw) <= 512 and 0 < len(right_raw) <= 512)
        or not isinstance(quantities_raw, dict)
        or len(quantities_raw) > 32
    ):
        raise ValueError("invalid_dimension_args")

    env: dict[str, DimVec] = {}
    for name, spec in quantities_raw.items():
        if not isinstance(name, str) or not name.isidentifier() or name in _DIMENSIONLESS_CONSTANTS:
            raise ValueError("invalid_quantity_name")
        env[name] = _parse_dim_spec(spec)

    left_tree = ast.parse(left_raw, mode="eval")
    right_tree = ast.parse(right_raw, mode="eval")
    if len(list(ast.walk(left_tree))) > 140 or len(list(ast.walk(right_tree))) > 140:
        raise ValueError("expression_too_large")

    try:
        left_dim = _eval_dim_tree(left_tree.body, env)
        right_dim = _eval_dim_tree(right_tree.body, env)
    except DimensionMismatch as mismatch:
        return {
            "engine_version": "physics-dim-v1",
            "status": "ok",
            "result": json.dumps(
                {"consistent": False, "reason": mismatch.reason},
                ensure_ascii=False,
            ),
            "conditions": [],
            "checked_scope": "equivalence",
            "verdict": "not_equal",
        }

    consistent = left_dim == right_dim
    payload = {
        "consistent": consistent,
        "left_dimension": _format_dim(left_dim),
        "right_dimension": _format_dim(right_dim),
    }
    return {
        "engine_version": "physics-dim-v1",
        "status": "ok",
        "result": json.dumps(payload, ensure_ascii=False),
        "conditions": [],
        "checked_scope": "equivalence",
        "verdict": "equal" if consistent else "not_equal",
    }
