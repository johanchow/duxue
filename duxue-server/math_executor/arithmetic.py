"""Bounded exact arithmetic shared by image review and isolated math execution."""

import ast
from decimal import Decimal, InvalidOperation
from fractions import Fraction


def arithmetic_equal(expression: str, submitted: str) -> bool:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ValueError("invalid_calculation_syntax") from error
    if len(list(ast.walk(tree))) > 80:
        raise ValueError("calculation_too_complex")

    def number(raw):
        parsed = Decimal(raw)
        if (
            not parsed.is_finite()
            or abs(parsed) > Decimal("1e12")
            or abs(parsed.as_tuple().exponent) > 24
        ):
            raise ValueError("calculation_out_of_bounds")
        return Fraction(parsed)

    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            result = number(ast.get_source_segment(expression, node))
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
        submitted = number(submitted)
        return value(tree.body) == submitted
    except (InvalidOperation, ArithmeticError) as error:
        raise ValueError("invalid_calculation") from error
