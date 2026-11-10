"""Restricted syntax -> explicit SymPy constructors. Never eval model input."""

from __future__ import annotations

import ast
import json
import re

import sympy as s

from math_executor.arithmetic import arithmetic_equal

MAX_TEXT = 512
FUNCTIONS = {
    "sin": s.sin,
    "cos": s.cos,
    "tan": s.tan,
    "exp": s.exp,
    "log": s.log,
    "sqrt": s.sqrt,
    "abs": s.Abs,
}
DOMAINS = {"real": s.S.Reals, "complex": s.S.Complexes, "integer": s.S.Integers}
PREDICATES = {"positive", "negative", "nonzero", "nonnegative"}


class Unsupported(ValueError):
    pass


class Parser:
    def __init__(self, symbols, assumptions):
        if (
            not isinstance(symbols, list)
            or len(symbols) > 8
            or not isinstance(assumptions, list)
            or len(assumptions) > 16
        ):
            raise ValueError("invalid_symbols")
        self.symbols, self.domains, self.conditions = {}, {}, set()
        predicates = {}
        for a in assumptions:
            if not isinstance(a, str) or a.count(":") != 1:
                raise ValueError("invalid_assumption")
            name, predicate = a.split(":")
            if predicate not in PREDICATES:
                raise ValueError("invalid_assumption")
            predicates.setdefault(name, {})[predicate] = True
        for item in symbols:
            if not isinstance(item, dict) or set(item) != {"name", "domain"}:
                raise ValueError("invalid_symbol")
            name, domain = item["name"], item["domain"]
            if not isinstance(name, str) or not re.fullmatch(
                "[a-zA-Z][a-zA-Z0-9]{0,15}", name
            ):
                raise ValueError("invalid_symbol")
            if (
                name in self.symbols
                or name in {*FUNCTIONS, "pi", "E", "oo"}
                or domain not in DOMAINS
            ):
                raise ValueError("invalid_symbol")
            self.symbols[name] = s.Symbol(
                name, **{domain: True}, **predicates.pop(name, {})
            )
            self.domains[name] = DOMAINS[domain]
        if predicates:
            raise ValueError("unknown_assumption_symbol")

    def parse(self, text):
        if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
            raise ValueError("invalid_expression")
        tree = ast.parse(text, mode="eval")
        if len(list(ast.walk(tree))) > 100:
            raise ValueError("expression_too_large")

        def visit(node, depth=0):
            if depth > 20:
                raise ValueError("expression_too_deep")
            sub = lambda child: visit(child, depth + 1)
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                raw = ast.get_source_segment(text, node)
                # Validate literal exponent BEFORE creating a potentially giant Rational.
                if len(raw) > 60 or not re.fullmatch(
                    r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,2})?", raw
                ):
                    raise ValueError("invalid_number")
                return s.Rational(raw)
            if isinstance(node, ast.Name):
                if node.id in self.symbols:
                    return self.symbols[node.id]
                if node.id in {"pi", "E", "oo"}:
                    return {"pi": s.pi, "E": s.E, "oo": s.oo}[node.id]
                raise ValueError("unknown_symbol")
            if isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.UAdd, ast.USub)
            ):
                val = sub(node.operand)
                return -val if isinstance(node.op, ast.USub) else val
            if isinstance(node, ast.BinOp):
                left, right = sub(node.left), sub(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    self.nonzero(left=right)
                    return left / right
                if isinstance(node.op, ast.Pow):
                    if right.is_Integer is not True or abs(right) > 100:
                        raise ValueError("exponent_limit")
                    if right < 0:
                        self.nonzero(left)
                    return left**right
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in FUNCTIONS
            ):
                if len(node.args) != 1 or node.keywords:
                    raise ValueError("invalid_function_args")
                arg = sub(node.args[0])
                if node.func.id in {"sqrt", "log"} and arg.is_real is True:
                    predicate = (
                        arg.is_nonnegative
                        if node.func.id == "sqrt"
                        else arg.is_positive
                    )
                    if predicate is False:
                        raise Unsupported("outside_real_domain")
                    if predicate is not True:
                        self.conditions.add(
                            f"{arg} {'>=' if node.func.id == 'sqrt' else '>'} 0"
                        )
                if node.func.id == "tan":
                    self.nonzero(s.cos(arg))
                return FUNCTIONS[node.func.id](arg)
            raise ValueError("unsupported_syntax")

        value = visit(tree.body)
        if value.has(s.zoo, s.nan):
            raise ValueError("undefined_expression")
        return value

    def nonzero(self, left):
        if left.is_zero is True:
            raise ValueError("division_by_zero")
        if left.is_zero is not False:
            self.conditions.add(f"{left} != 0")

    def variable(self, name):
        if name not in self.symbols:
            raise ValueError("undeclared_variable")
        return self.symbols[name]


def execute(request):
    """Always a wire-safe, bounded status; unknown is never a negative verdict."""
    scope = "value"
    try:
        op, args = request["op"], request["args"]
        if not isinstance(args, dict):
            raise TypeError("invalid_args")
        required = {
            "evaluate": {"expression"},
            "equivalent": {"left", "right"},
            "solve": {"equations", "variables"},
            "differentiate": {"expression", "variable", "order"},
            "integrate": {"expression", "variable"},
            "limit": {"expression", "variable", "point", "direction"},
        }
        optional = {"evaluate": {"precision"}, "integrate": {"bounds"}}
        if op not in required:
            raise Unsupported("operation")
        if not required[op] <= set(args) or set(args) - required[op] - optional.get(
            op, set()
        ):
            raise ValueError("invalid_args")
        p = Parser(request.get("symbols", []), request.get("assumptions", []))
        verdict = None
        if op == "equivalent":
            scope = "equivalence"
            left, right = p.parse(args["left"]), p.parse(args["right"])
            diff = s.simplify(left - right)
            if not p.symbols:
                try:
                    equal = arithmetic_equal(args["left"], args["right"])
                    return {
                        "status": "ok",
                        "result": str(diff),
                        "conditions": [],
                        "checked_scope": scope,
                        "verdict": "equal" if equal else "not_equal",
                    }
                except ValueError:
                    pass
            # Unproven domains must not disappear through SymPy cancellation.
            verdict = (
                "unknown"
                if p.conditions
                else "equal"
                if diff == 0
                else "not_equal"
                if not diff.free_symbols and diff.is_zero is False
                else "unknown"
            )
            result = diff
        elif op == "solve":
            scope = "solution_set"
            if not isinstance(args["equations"], list) or not isinstance(
                args["variables"], list
            ):
                raise ValueError("invalid_solve_args")
            # A deliberately bounded v1: one univariate equation, written as lhs-rhs.
            if len(args["equations"]) != 1 or len(args["variables"]) != 1:
                raise Unsupported("univariate_only")
            var = p.variable(args["variables"][0])
            expr = p.parse(args["equations"][0])
            if expr.free_symbols - {var}:
                raise Unsupported("parameterized_equation")
            result = s.solveset(expr, var, domain=p.domains[str(var)])
            if result.has(s.ConditionSet) or p.conditions:
                raise Unsupported("unresolved_solution_conditions")
        else:
            expr = p.parse(args["expression"])
            if op == "evaluate":
                if expr.free_symbols:
                    raise Unsupported("not_numeric")
                result = expr
                if "precision" in args:
                    digits = args["precision"]
                    if type(digits) is not int or not 1 <= digits <= 50:
                        raise ValueError("precision_limit")
                    result = s.N(expr, digits)
            elif op == "differentiate":
                order = args["order"]
                if type(order) is not int or not 1 <= order <= 5:
                    raise ValueError("order_limit")
                result = s.diff(expr, p.variable(args["variable"]), order)
            elif op == "integrate":
                var = p.variable(args["variable"])
                bounds = args.get("bounds")
                if bounds is not None:
                    if not isinstance(bounds, list) or len(bounds) != 2:
                        raise ValueError("invalid_bounds")
                    result = s.integrate(expr, (var, *(p.parse(b) for b in bounds)))
                else:
                    result = s.integrate(expr, var)
                    p.conditions.add("antiderivative_family: result + C")
            else:
                if args["direction"] not in ("+", "-", "+-"):
                    raise ValueError("invalid_direction")
                result = s.limit(
                    expr,
                    p.variable(args["variable"]),
                    p.parse(args["point"]),
                    dir=args["direction"],
                )
        if result.has(s.Integral, s.Derivative, s.Limit, s.ConditionSet, s.nan, s.zoo):
            raise Unsupported("unevaluated")
        rendered = str(result)
        if len(rendered) > 4096:
            raise ValueError("output_limit")
        response = {
            "engine_version": "sympy-" + s.__version__,
            "status": "unknown" if verdict == "unknown" else "ok",
            "result": rendered,
            "conditions": sorted(p.conditions),
            "checked_scope": scope,
        }
        if verdict is not None:
            response["verdict"] = verdict
        return response
    except (Unsupported, NotImplementedError):
        return {
            "status": "unknown",
            "error_code": "unsupported",
            "conditions": [],
            "checked_scope": scope,
        }
    except Exception:  # noqa: BLE001 - untrusted computation boundary returns no exception text
        return {
            "status": "error",
            "error_code": "invalid_input",
            "conditions": [],
            "checked_scope": scope,
        }


if __name__ == "__main__":
    import sys

    request = json.loads(sys.stdin.buffer.read(16385))
    print(json.dumps(execute(request)))
