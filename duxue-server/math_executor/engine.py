"""Restricted syntax -> explicit SymPy constructors. Never eval model input."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from math_executor.arithmetic import arithmetic_equal, arithmetic_eval, format_fraction

MAX_TEXT = 512
MAX_NODES = 140
MAX_DEPTH = 24
PREDICATES = {"positive", "negative", "nonzero", "nonnegative"}
_RESERVED_CONSTANTS = {"pi", "E", "oo", "I"}
_UNARY_NAMES = {
    "sin",
    "cos",
    "tan",
    "cot",
    "asin",
    "acos",
    "atan",
    "exp",
    "ln",
    "sqrt",
    "cbrt",
    "abs",
    "re",
    "im",
    "conjugate",
    "factorial",
}
_MULTI_NAMES = {"log", "root", "binomial", "gcd", "lcm", "dot", "norm", "cross"}
_RESERVED_NAMES = _RESERVED_CONSTANTS | _UNARY_NAMES | _MULTI_NAMES


class Unsupported(ValueError):
    pass


def _fast_arithmetic(request: dict[str, Any]) -> dict[str, Any] | None:
    """Handle pure exact four-operation arithmetic before importing SymPy."""
    if request.get("symbols") or request.get("assumptions"):
        return None
    op = request.get("op")
    args = request.get("args")
    if not isinstance(args, dict):
        return None
    if op == "evaluate" and set(args) == {"expression"}:
        expr = args.get("expression")
        if not isinstance(expr, str) or not 0 < len(expr) <= MAX_TEXT:
            return None
        try:
            val = arithmetic_eval(expr)
        except ValueError:
            return None
        return {
            "engine_version": "arithmetic-v1",
            "status": "ok",
            "result": format_fraction(val),
            "conditions": [],
            "checked_scope": "value",
        }
    if op == "equivalent" and set(args) == {"left", "right"}:
        left, right = args.get("left"), args.get("right")
        if (
            not isinstance(left, str)
            or not isinstance(right, str)
            or not (0 < len(left) <= MAX_TEXT and 0 < len(right) <= MAX_TEXT)
        ):
            return None
        try:
            lv, rv = arithmetic_eval(left), arithmetic_eval(right)
        except ValueError:
            return None
        diff = lv - rv
        return {
            "engine_version": "arithmetic-v1",
            "status": "ok",
            "result": format_fraction(diff),
            "conditions": [],
            "checked_scope": "equivalence",
            "verdict": "equal" if diff == 0 else "not_equal",
        }
    return None


class Parser:
    def __init__(self, sym, symbols, assumptions):
        self.s = sym
        domains = {
            "real": sym.S.Reals,
            "complex": sym.S.Complexes,
            "integer": sym.S.Integers,
        }
        if (
            not isinstance(symbols, list)
            or len(symbols) > 8
            or not isinstance(assumptions, list)
            or len(assumptions) > 16
        ):
            raise ValueError("invalid_symbols")
        self.symbols, self.domains, self.conditions = {}, {}, set()
        self.domain_guards: list[tuple[str, Any]] = []
        predicates: dict[str, dict[str, bool]] = {}
        for item in assumptions:
            if not isinstance(item, str) or item.count(":") != 1:
                raise ValueError("invalid_assumption")
            name, predicate = item.split(":")
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
            if name in self.symbols or name in _RESERVED_NAMES or domain not in domains:
                raise ValueError("invalid_symbol")
            self.symbols[name] = sym.Symbol(
                name, **{domain: True}, **predicates.pop(name, {})
            )
            self.domains[name] = domains[domain]
        if predicates:
            raise ValueError("unknown_assumption_symbol")

    def _check_nonnegative(self, expr):
        if expr.is_real is True:
            if expr.is_nonnegative is False:
                raise Unsupported("outside_real_domain")
            if expr.is_nonnegative is not True:
                self.conditions.add(f"{expr} >= 0")
                self.domain_guards.append((">=", expr))

    def _check_positive(self, expr):
        if expr.is_real is True:
            if expr.is_positive is False:
                raise Unsupported("outside_real_domain")
            if expr.is_positive is not True:
                self.conditions.add(f"{expr} > 0")
                self.domain_guards.append((">", expr))

    def nonzero(self, left):
        if left.is_zero is True:
            raise ValueError("division_by_zero")
        if left.is_zero is not False:
            self.conditions.add(f"{left} != 0")
            self.domain_guards.append(("!=", left))

    def variable(self, name):
        if not isinstance(name, str) or name not in self.symbols:
            raise ValueError("undeclared_variable")
        return self.symbols[name]

    def _parse_vector_arg(self, text: str, node: ast.AST, visit_fn) -> tuple[Any, ...]:
        if isinstance(node, (ast.List, ast.Tuple)):
            if len(node.elts) not in (2, 3):
                raise ValueError("invalid_vector_dimension")
            return tuple(visit_fn(elt) for elt in node.elts)
        val = visit_fn(node)
        if isinstance(val, self.s.Tuple) and len(val) in (2, 3):
            return tuple(val)
        raise ValueError("invalid_vector_argument")

    def _visit_expr(self, text: str, node: ast.AST, depth: int = 0):
        s = self.s
        if depth > MAX_DEPTH:
            raise ValueError("expression_too_deep")
        sub = lambda child: self._visit_expr(text, child, depth + 1)

        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            raw = ast.get_source_segment(text, node)
            if (
                raw is None
                or len(raw) > 60
                or not re.fullmatch(
                    r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,2})?", raw
                )
            ):
                raise ValueError("invalid_number")
            return s.Rational(raw)

        if isinstance(node, ast.Name):
            if node.id in self.symbols:
                return self.symbols[node.id]
            if node.id in _RESERVED_CONSTANTS:
                return {"pi": s.pi, "E": s.E, "oo": s.oo, "I": s.I}[node.id]
            raise ValueError("unknown_symbol")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            val = sub(node.operand)
            if isinstance(val, s.Tuple):
                raise ValueError("unsupported_syntax")
            return -val if isinstance(node.op, ast.USub) else val

        if isinstance(node, ast.BinOp):
            left, right = sub(node.left), sub(node.right)
            if isinstance(left, s.Tuple) or isinstance(right, s.Tuple):
                raise ValueError("unsupported_syntax")
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
                if not right.free_symbols:
                    if right.is_Integer is True:
                        if abs(int(right)) > 200:
                            raise ValueError("exponent_limit")
                        if right < 0:
                            self.nonzero(left)
                        return left**right
                    if right.is_Rational is True:
                        if abs(int(right.p)) > 200 or int(right.q) > 100:
                            raise ValueError("exponent_limit")
                        if right < 0:
                            self.nonzero(left)
                        if int(right.q) % 2 == 0:
                            self._check_nonnegative(left)
                        elif left.is_real is True and left.is_negative is True:
                            raise Unsupported("ambiguous_negative_fractional_power")
                        elif left.is_real is True and left.is_nonnegative is not True:
                            self._check_nonnegative(left)
                        return left**right
                    if left == s.E or (left.is_real is True and left.is_positive is True):
                        return left**right
                    raise ValueError("exponent_limit")
                # Symbolic exponent (e.g. 2**(2*n-1), a**x).
                if left.is_Integer is True and abs(int(left)) > 1000:
                    raise ValueError("exponent_limit")
                if left.is_real is True:
                    if left.is_positive is True:
                        return left**right
                    if right.is_integer is True:
                        if right.is_nonnegative is not True:
                            self.nonzero(left)
                        return left**right
                    self._check_positive(left)
                return left**right

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and not node.keywords
        ):
            fn = node.func.id
            nargs = len(node.args)
            if fn in {"dot", "norm", "cross"}:
                if fn == "norm" and nargs == 1:
                    u = self._parse_vector_arg(text, node.args[0], sub)
                    return s.sqrt(
                        sum(
                            x**2 if x.is_real is True else s.Abs(x) ** 2
                            for x in u
                        )
                    )
                if fn == "dot" and nargs == 2:
                    u = self._parse_vector_arg(text, node.args[0], sub)
                    v = self._parse_vector_arg(text, node.args[1], sub)
                    if len(u) != len(v):
                        raise ValueError("vector_dimension_mismatch")
                    return sum(a * b for a, b in zip(u, v))
                if fn == "cross" and nargs == 2:
                    u = self._parse_vector_arg(text, node.args[0], sub)
                    v = self._parse_vector_arg(text, node.args[1], sub)
                    if len(u) != 3 or len(v) != 3:
                        raise ValueError("cross_requires_3d_vectors")
                    return s.Tuple(
                        u[1] * v[2] - u[2] * v[1],
                        u[2] * v[0] - u[0] * v[2],
                        u[0] * v[1] - u[1] * v[0],
                    )
                raise ValueError("invalid_function_args")

            if fn == "log" and nargs in (1, 2):
                arg = sub(node.args[0])
                self._check_positive(arg)
                if nargs == 1:
                    return s.log(arg)
                base = sub(node.args[1])
                self._check_positive(base)
                self.nonzero(base - 1)
                return s.log(arg, base)

            if fn == "root" and nargs == 2:
                arg, degree = sub(node.args[0]), sub(node.args[1])
                if degree.is_Integer is not True or not 1 <= int(degree) <= 100:
                    raise ValueError("invalid_root_degree")
                n = int(degree)
                if n % 2 == 0:
                    self._check_nonnegative(arg)
                    return s.root(arg, n)
                if arg.is_Number and arg.is_real is True:
                    return s.real_root(arg, n)
                return s.cbrt(arg) if n == 3 else s.root(arg, n)

            if fn == "binomial" and nargs == 2:
                n_val, k_val = sub(node.args[0]), sub(node.args[1])
                if n_val.is_Integer is True and k_val.is_Integer is True:
                    ni, ki = int(n_val), int(k_val)
                    if ni < 0 or ni > 10000 or ki < 0 or ki > ni:
                        raise ValueError("binomial_domain_or_limit")
                    if min(ki, ni - ki) > 500:
                        raise ValueError("binomial_domain_or_limit")
                    return s.binomial(ni, ki)
                if n_val.is_integer is True and k_val.is_integer is True:
                    if k_val.is_nonnegative is not True:
                        self.conditions.add(f"{k_val} >= 0")
                    if (n_val - k_val).is_nonnegative is not True:
                        self.conditions.add(f"{n_val} - ({k_val}) >= 0")
                    return s.binomial(n_val, k_val)
                raise Unsupported("binomial_requires_integers")

            if fn in {"gcd", "lcm"} and nargs == 2:
                a, b = sub(node.args[0]), sub(node.args[1])
                if (
                    a.is_Integer is not True
                    or b.is_Integer is not True
                    or abs(int(a)) > 10**15
                    or abs(int(b)) > 10**15
                ):
                    raise ValueError("integer_limit")
                return s.igcd(a, b) if fn == "gcd" else s.ilcm(a, b)

            if fn in _UNARY_NAMES and nargs == 1:
                arg = sub(node.args[0])
                if isinstance(arg, s.Tuple):
                    raise ValueError("invalid_function_args")
                if fn == "sqrt":
                    self._check_nonnegative(arg)
                    return s.sqrt(arg)
                if fn == "cbrt":
                    return (
                        s.real_root(arg, 3)
                        if arg.is_Number and arg.is_real is True
                        else s.cbrt(arg)
                    )
                if fn == "ln":
                    self._check_positive(arg)
                    return s.log(arg)
                if fn == "tan":
                    self.nonzero(s.cos(arg))
                    return s.tan(arg)
                if fn == "cot":
                    self.nonzero(s.sin(arg))
                    return s.cot(arg)
                if fn in {"asin", "acos"}:
                    if arg.is_real is True:
                        inside = (1 - s.Abs(arg)).is_nonnegative
                        if inside is False:
                            raise Unsupported("outside_real_domain")
                        if inside is not True:
                            self.conditions.add(f"Abs({arg}) <= 1")
                            self.domain_guards.append((">=", 1 - s.Abs(arg)))
                    return s.asin(arg) if fn == "asin" else s.acos(arg)
                if fn == "atan":
                    return s.atan(arg)
                if fn == "factorial":
                    if arg.is_Integer is True:
                        iv = int(arg)
                        if iv < 0 or iv > 200:
                            raise ValueError("factorial_limit")
                        return s.factorial(iv)
                    if arg.is_integer is True:
                        if arg.is_nonnegative is False:
                            raise Unsupported("outside_real_domain")
                        if arg.is_nonnegative is not True:
                            self.conditions.add(f"{arg} >= 0")
                        return s.factorial(arg)
                    raise Unsupported("factorial_requires_integer")
                return {
                    "sin": s.sin,
                    "cos": s.cos,
                    "exp": s.exp,
                    "abs": s.Abs,
                    "re": s.re,
                    "im": s.im,
                    "conjugate": s.conjugate,
                }[fn](arg)

            raise ValueError("invalid_function_args")

        raise ValueError("unsupported_syntax")

    def parse(self, text: str, *, allow_tuple: bool = False):
        if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
            raise ValueError("invalid_expression")
        tree = ast.parse(text, mode="eval")
        if len(list(ast.walk(tree))) > MAX_NODES:
            raise ValueError("expression_too_large")
        value = self._visit_expr(text, tree.body)
        if isinstance(value, self.s.Tuple) and not allow_tuple:
            raise ValueError("unsupported_syntax")
        if value.has(self.s.zoo, self.s.nan):
            raise ValueError("undefined_expression")
        return value

    def parse_equation_or_relations(
        self, text: str
    ) -> tuple[list[Any], list[Any]]:
        """Parse an algebraic equation (`expr` or `lhs == rhs`) or inequality chain."""
        s = self.s
        if not isinstance(text, str) or not 0 < len(text) <= MAX_TEXT:
            raise ValueError("invalid_expression")
        normalized = re.sub(r"(?<![<>!=])=(?!=)", "==", text)
        tree = ast.parse(normalized, mode="eval")
        if len(list(ast.walk(tree))) > MAX_NODES:
            raise ValueError("expression_too_large")
        body = tree.body
        if isinstance(body, ast.Compare):
            operands = [body.left, *body.comparators]
            exprs = [self._visit_expr(normalized, op_node) for op_node in operands]
            if any(
                isinstance(e, s.Tuple) or e.has(s.zoo, s.nan) for e in exprs
            ):
                raise ValueError("undefined_expression")
            equations: list[Any] = []
            inequalities: list[Any] = []
            for left, op, right in zip(exprs, body.ops, exprs[1:]):
                if isinstance(op, ast.Eq):
                    equations.append(left - right)
                elif isinstance(op, ast.Lt):
                    inequalities.append(s.StrictLessThan(left, right))
                elif isinstance(op, ast.LtE):
                    inequalities.append(s.LessThan(left, right))
                elif isinstance(op, ast.Gt):
                    inequalities.append(s.StrictGreaterThan(left, right))
                elif isinstance(op, ast.GtE):
                    inequalities.append(s.GreaterThan(left, right))
                elif isinstance(op, ast.NotEq):
                    inequalities.append(s.Ne(left, right))
                else:
                    raise ValueError("unsupported_comparison")
            return equations, inequalities
        expr = self._visit_expr(normalized, body)
        if isinstance(expr, s.Tuple) or expr.has(s.zoo, s.nan):
            raise ValueError("undefined_expression")
        return [expr], []


def _solution_satisfies_domains_and_guards(
    s,
    sol: dict[Any, Any],
    vars_sym: list[Any],
    domains: dict[str, Any],
    guards: list[tuple[str, Any]],
) -> tuple[bool, set[str]]:
    """Return (keep_solution, remaining_symbolic_conditions)."""
    remaining: set[str] = set()
    for var in vars_sym:
        val = sol[var]
        if val.has(s.zoo, s.nan, s.oo, -s.oo):
            return False, set()
        dom = domains[str(var)]
        if dom == s.S.Reals:
            if val.is_real is False:
                return False, set()
            if val.is_real is None and val.has(s.I):
                simplified = s.simplify(val)
                if simplified.is_real is False:
                    return False, set()
                sol[var] = simplified
        elif dom == s.S.Integers:
            if val.is_integer is False:
                return False, set()
            if val.is_integer is None:
                return False, set()
    for kind, guard_expr in guards:
        substituted = s.simplify(guard_expr.subs(sol))
        if substituted.has(s.zoo, s.nan):
            return False, set()
        if kind == "!=":
            if substituted.is_zero is True:
                return False, set()
            if substituted.is_zero is not False:
                remaining.add(f"{substituted} != 0")
        elif kind == ">=":
            if substituted.is_nonnegative is False:
                return False, set()
            if substituted.is_nonnegative is not True:
                remaining.add(f"{substituted} >= 0")
        elif kind == ">":
            if substituted.is_positive is False:
                return False, set()
            if substituted.is_positive is not True:
                remaining.add(f"{substituted} > 0")
    return True, remaining


def _solve_operation(s, p: Parser, args: dict[str, Any]) -> tuple[Any, set[str]]:
    raw_eqs = args["equations"]
    raw_vars = args["variables"]
    if (
        not isinstance(raw_eqs, list)
        or not isinstance(raw_vars, list)
        or not 1 <= len(raw_eqs) <= 6
        or not 1 <= len(raw_vars) <= 4
        or len(set(raw_vars)) != len(raw_vars)
    ):
        raise ValueError("invalid_solve_args")
    vars_sym = [p.variable(v) for v in raw_vars]
    equations: list[Any] = []
    inequalities: list[Any] = []
    for item in raw_eqs:
        eqs, ineqs = p.parse_equation_or_relations(item)
        equations.extend(eqs)
        inequalities.extend(ineqs)

    all_exprs = [*equations, *inequalities]
    extra_params = set().union(*(e.free_symbols for e in all_exprs)) - set(vars_sym)

    # Branch 1: Inequalities (univariate real domain).
    if inequalities:
        if len(vars_sym) != 1 or p.domains[str(vars_sym[0])] != s.S.Reals:
            raise Unsupported("univariate_real_inequality_only")
        if extra_params:
            raise Unsupported("parameterized_inequality")
        var = vars_sym[0]
        rels = list(inequalities) + [s.Eq(eq, 0) for eq in equations]
        for kind, guard_expr in p.domain_guards:
            if kind == "!=":
                rels.append(s.Ne(guard_expr, 0))
            elif kind == ">=":
                rels.append(s.GreaterThan(guard_expr, 0))
            elif kind == ">":
                rels.append(s.StrictGreaterThan(guard_expr, 0))
        solved = s.reduce_inequalities(rels, var)
        return solved, set()

    # Branch 2: Univariate non-parameterized equation without domain guards -> exact solveset.
    if len(equations) == 1 and len(vars_sym) == 1 and not extra_params and not p.domain_guards:
        var = vars_sym[0]
        result = s.solveset(equations[0], var, domain=p.domains[str(var)])
        if result.has(s.ConditionSet) or p.conditions:
            raise Unsupported("unresolved_solution_conditions")
        return result, set()

    # Branch 3: Systems of equations, parameterized equations, or guarded rational/radical equations.
    try:
        raw_solutions = s.solve(equations, vars_sym, dict=True)
    except NotImplementedError as error:
        raise Unsupported("unsolved_system") from error
    if not isinstance(raw_solutions, list):
        raise Unsupported("unsolved_system")

    valid_solutions: list[dict[Any, Any]] = []
    out_conditions: set[str] = set()
    for candidate in raw_solutions:
        if set(candidate.keys()) != set(vars_sym):
            raise Unsupported("underdetermined_system")
        sol = {k: s.simplify(v) for k, v in candidate.items()}
        keep, rem = _solution_satisfies_domains_and_guards(
            s, sol, vars_sym, p.domains, p.domain_guards
        )
        if keep:
            valid_solutions.append(sol)
            out_conditions.update(rem)

    # Check if linear parameter degeneracy could vanish a leading coefficient in original equations.
    if extra_params:
        for sol in valid_solutions:
            for val in sol.values():
                _, denom = val.as_numer_denom()
                if denom.free_symbols:
                    out_conditions.add(f"{denom} != 0")

    if not valid_solutions and extra_params:
        raise Unsupported("parameterized_empty_or_conditional")

    if len(vars_sym) == 1:
        var = vars_sym[0]
        return s.FiniteSet(*(sol[var] for sol in valid_solutions)), out_conditions

    formatted = [
        "{" + ", ".join(f"{v}: {sol[v]}" for v in vars_sym) + "}"
        for sol in valid_solutions
    ]
    return "{" + ", ".join(sorted(dict.fromkeys(formatted))) + "}", out_conditions


def execute(request):
    """Always a wire-safe, bounded status; unknown is never a negative verdict."""
    scope = "value"
    engine_ver = "sympy"
    try:
        if not isinstance(request, dict):
            raise TypeError("invalid_request")
        op, args = request["op"], request["args"]
        if not isinstance(args, dict):
            raise TypeError("invalid_args")
        if op == "equivalent":
            scope = "equivalence"
        elif op == "solve":
            scope = "solution_set"

        fast = _fast_arithmetic(request)
        if fast is not None:
            return fast

        import sympy as s

        engine_ver = "sympy-" + s.__version__
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
        p = Parser(s, request.get("symbols", []), request.get("assumptions", []))
        verdict = None
        out_conditions = set(p.conditions)

        if op == "equivalent":
            left, right = p.parse(args["left"]), p.parse(args["right"])
            raw_diff = left - right
            diff = s.simplify(s.expand_log(raw_diff))
            if diff != 0:
                diff = s.simplify(raw_diff)
            if not p.symbols and not diff.has(s.I):
                try:
                    equal = arithmetic_equal(args["left"], args["right"])
                    return {
                        "engine_version": engine_ver,
                        "status": "ok",
                        "result": str(diff),
                        "conditions": [],
                        "checked_scope": scope,
                        "verdict": "equal" if equal else "not_equal",
                    }
                except ValueError:
                    pass
            out_conditions = set(p.conditions)
            # Unproven domains must not disappear through SymPy cancellation.
            verdict = (
                "unknown"
                if out_conditions
                else "equal"
                if diff == 0
                else "not_equal"
                if not diff.free_symbols and diff.is_zero is False
                else "unknown"
            )
            result = diff
        elif op == "solve":
            result, out_conditions = _solve_operation(s, p, args)
        else:
            expr = p.parse(args["expression"], allow_tuple=(op == "evaluate"))
            out_conditions = set(p.conditions)
            if op == "evaluate":
                if expr.free_symbols:
                    raise Unsupported("not_numeric")
                result = s.simplify(expr) if not isinstance(expr, s.Tuple) else expr
                if "precision" in args:
                    if isinstance(expr, s.Tuple):
                        raise ValueError("precision_limit")
                    digits = args["precision"]
                    if type(digits) is not int or not 1 <= digits <= 50:
                        raise ValueError("precision_limit")
                    result = s.N(result, digits)
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
                    b0, b1 = (p.parse(b) for b in bounds)
                    out_conditions = set(p.conditions)
                    result = s.integrate(expr, (var, b0, b1))
                else:
                    result = s.integrate(expr, var)
                    out_conditions.add("antiderivative_family: result + C")
            else:
                if args["direction"] not in ("+", "-", "+-"):
                    raise ValueError("invalid_direction")
                pt = p.parse(args["point"])
                out_conditions = set(p.conditions)
                result = s.limit(
                    expr,
                    p.variable(args["variable"]),
                    pt,
                    dir=args["direction"],
                )

        if hasattr(result, "has") and result.has(
            s.Integral, s.Derivative, s.Limit, s.ConditionSet, s.nan, s.zoo
        ):
            raise Unsupported("unevaluated")
        rendered = result if isinstance(result, str) else str(result)
        if len(rendered) > 4096:
            raise ValueError("output_limit")
        response = {
            "engine_version": engine_ver,
            "status": "unknown" if verdict == "unknown" else "ok",
            "result": rendered,
            "conditions": sorted(out_conditions),
            "checked_scope": scope,
        }
        if verdict is not None:
            response["verdict"] = verdict
        return response
    except (Unsupported, NotImplementedError):
        return {
            "engine_version": engine_ver,
            "status": "unknown",
            "error_code": "unsupported",
            "conditions": [],
            "checked_scope": scope,
        }
    except Exception:  # noqa: BLE001 - untrusted computation boundary returns no exception text
        return {
            "engine_version": engine_ver,
            "status": "error",
            "error_code": "invalid_input",
            "conditions": [],
            "checked_scope": scope,
        }


if __name__ == "__main__":
    import sys

    request = json.loads(sys.stdin.buffer.read(16385))
    print(json.dumps(execute(request)))
