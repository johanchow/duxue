"""Bounded exact arithmetic shared by image review and isolated math execution."""

from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
from fractions import Fraction


def _parse_number(raw: str) -> Fraction:
    try:
        parsed = Decimal(raw)
        if (
            not parsed.is_finite()
            or abs(parsed) > Decimal("1e12")
            or abs(parsed.as_tuple().exponent) > 24
        ):
            raise ValueError("calculation_out_of_bounds")
        return Fraction(parsed)
    except (InvalidOperation, ArithmeticError) as error:
        raise ValueError("invalid_calculation") from error


def arithmetic_eval(expression: str) -> Fraction:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ValueError("invalid_calculation_syntax") from error
    if len(list(ast.walk(tree))) > 80:
        raise ValueError("calculation_too_complex")

    def value(node: ast.AST) -> Fraction:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            segment = ast.get_source_segment(expression, node)
            if segment is None:
                raise ValueError("invalid_calculation_syntax")
            result = _parse_number(segment)
        elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            result = value(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            else:
                result = left / right
        else:
            raise ValueError("unsupported_calculation_syntax")
        if abs(result) > 10**12 or result.denominator.bit_length() > 1024:
            raise ValueError("calculation_out_of_bounds")
        return result

    try:
        return value(tree.body)
    except (InvalidOperation, ArithmeticError) as error:
        raise ValueError("invalid_calculation") from error


def format_fraction(value: Fraction) -> str:
    return (
        str(value.numerator)
        if value.denominator == 1
        else f"{value.numerator}/{value.denominator}"
    )


def arithmetic_equal(expression: str, submitted: str) -> bool:
    try:
        target = _parse_number(submitted.strip())
    except (InvalidOperation, ValueError):
        target = arithmetic_eval(submitted)
    return arithmetic_eval(expression) == target
