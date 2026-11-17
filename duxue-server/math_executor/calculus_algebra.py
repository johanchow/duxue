"""High-school calculus, algebraic transformation, conic Vieta, and 3D vector geometry."""

from __future__ import annotations

import json
import re
from typing import Any


def transform_operation(s, p, args: dict[str, Any]) -> tuple[Any, set[str]]:
    expr = p.parse(args["expression"])
    mode = args["mode"]
    out_conditions = set(p.conditions)
    if mode == "simplify":
        return s.simplify(expr), out_conditions
    if mode == "factor":
        return s.factor(expr), out_conditions
    if mode == "expand":
        return s.expand(expr), out_conditions
    if mode == "trigsimp":
        return s.trigsimp(expr), out_conditions
    if mode == "together":
        return s.together(expr), out_conditions
    if mode == "apart":
        var = p.variable(args["variable"]) if "variable" in args else None
        return (s.apart(expr, var) if var is not None else s.apart(expr)), out_conditions
    raise ValueError("invalid_transform_mode")


def summation_operation(s, p, args: dict[str, Any]) -> tuple[Any, set[str]]:
    expr = p.parse(args["expression"])
    var = p.variable(args["variable"])
    start = p.parse(args["start"])
    end = p.parse(args["end"])
    out_conditions = set(p.conditions)
    if start.is_Integer is True and end.is_Integer is True:
        span = int(end) - int(start)
        if span > 10000:
            raise ValueError("summation_span_limit")
        if span < -1:
            raise ValueError("invalid_summation_bounds")
    result = s.summation(expr, (var, start, end))
    if result.has(s.Sum, s.zoo, s.nan):
        from math_executor.engine import Unsupported

        raise Unsupported("unevaluated_sum")
    return s.simplify(result), out_conditions


def _parse_real_interval(s, p, raw: str | None):
    if raw is None:
        return s.S.Reals
    if not isinstance(raw, str) or len(raw) > 120:
        raise ValueError("invalid_domain_interval")
    text = raw.strip()
    match = re.fullmatch(r"([(\[])\s*([^,]+)\s*,\s*([^,\])]+)\s*([)\]])", text)
    if not match:
        raise ValueError("invalid_domain_interval")
    left_br, left_raw, right_raw, right_br = match.groups()
    left = -s.oo if left_raw.strip() in {"-oo", "-inf"} else p.parse(left_raw.strip())
    right = s.oo if right_raw.strip() in {"oo", "+oo", "inf", "+inf"} else p.parse(right_raw.strip())
    if left.free_symbols or right.free_symbols:
        from math_executor.engine import Unsupported

        raise Unsupported("symbolic_domain_interval")
    left_open = left_br == "(" or left == -s.oo
    right_open = right_br == ")" or right == s.oo
    iv = s.Interval(left, right, left_open=left_open, right_open=right_open)
    if iv.is_empty:
        raise ValueError("empty_domain_interval")
    return iv


def _sample_point(s, left, right):
    if left == -s.oo and right == s.oo:
        return s.Integer(0)
    if left == -s.oo:
        return right - s.Integer(1)
    if right == s.oo:
        return left + s.Integer(1)
    return (left + right) / s.Integer(2)


def _format_open_interval(s, left, right) -> str:
    l_str = "-oo" if left == -s.oo else str(left)
    r_str = "oo" if right == s.oo else str(right)
    return f"({l_str}, {r_str})"


def analyze_function_operation(s, p, args: dict[str, Any]) -> tuple[str, set[str]]:
    from math_executor.engine import Unsupported

    var = p.variable(args["variable"])
    if p.domains[str(var)] != s.S.Reals:
        raise Unsupported("real_variable_required")
    expr = p.parse(args["expression"])
    extra_symbols = expr.free_symbols - {var}
    if extra_symbols:
        raise Unsupported("parameterized_monotonicity_requires_case_split")
    domain_iv = _parse_real_interval(s, p, args.get("domain_interval"))
    out_conditions = set(p.conditions)

    # Intersect with natural continuous domain inside domain_iv.
    from sympy.calculus.util import continuous_domain

    cont_dom = continuous_domain(expr, var, domain_iv)
    deriv = s.simplify(s.diff(expr, var))
    factored_deriv = s.factor(deriv)

    zeros = s.solveset(deriv, var, domain=cont_dom)
    raw_sing = s.singularities(expr, var) | s.singularities(deriv, var)
    singulars = raw_sing.intersect(domain_iv)
    if not (zeros.is_empty or isinstance(zeros, s.FiniteSet)) or not (
        singulars.is_empty or isinstance(singulars, s.FiniteSet)
    ):
        raise Unsupported("non_finite_critical_set")

    pts_map: dict[float, Any] = {}
    for pt in list(zeros) + list(singulars):
        if pt.is_real is not True or pt in (-s.oo, s.oo):
            continue
        if domain_iv.contains(pt) != s.S.true and pt not in (domain_iv.start, domain_iv.end):
            continue
        if pt in (domain_iv.start, domain_iv.end):
            continue
        pts_map[float(pt.evalf())] = s.simplify(pt)

    sorted_pts = [pts_map[k] for k in sorted(pts_map)]
    critical_zeros = [
        str(pt) for pt in sorted_pts if zeros.contains(pt) == s.S.true
    ]

    boundaries = [domain_iv.start, *sorted_pts, domain_iv.end]
    intervals = []
    for left, right in zip(boundaries, boundaries[1:]):
        mid = _sample_point(s, left, right)
        if cont_dom.contains(mid) != s.S.true:
            continue
        val = deriv.subs(var, mid).evalf()
        if not val.is_real:
            raise Unsupported("complex_derivative_sample")
        fval = float(val)
        sign = "0" if abs(fval) < 1e-15 else ("+" if fval > 0 else "-")
        monotonicity = (
            "constant" if sign == "0" else ("increasing" if sign == "+" else "decreasing")
        )
        intervals.append(
            {
                "interval": _format_open_interval(s, left, right),
                "sign": sign,
                "monotonicity": monotonicity,
            }
        )

    extrema = []
    for pt in sorted_pts:
        if zeros.contains(pt) != s.S.true or cont_dom.contains(pt) != s.S.true:
            continue
        # Match adjacent intervals around pt
        left_sign = next(
            (iv["sign"] for iv in intervals if iv["interval"].endswith(f", {pt})")),
            None,
        )
        right_sign = next(
            (iv["sign"] for iv in intervals if iv["interval"].startswith(f"({pt}, ")),
            None,
        )
        if left_sign == "+" and right_sign == "-":
            extrema.append({"point": str(pt), "kind": "local_max", "value": str(s.simplify(expr.subs(var, pt)))})
        elif left_sign == "-" and right_sign == "+":
            extrema.append({"point": str(pt), "kind": "local_min", "value": str(s.simplify(expr.subs(var, pt)))})

    payload = {
        "derivative": str(deriv),
        "factored_derivative": str(factored_deriv),
        "critical_points": critical_zeros,
        "intervals": intervals,
        "extrema": extrema,
    }
    return json.dumps(payload, ensure_ascii=False), out_conditions


def conic_line_operation(s, p, args: dict[str, Any]) -> tuple[str, set[str]]:
    from math_executor.engine import Unsupported

    raw_vars = args["variables"]
    if (
        not isinstance(raw_vars, list)
        or len(raw_vars) != 2
        or raw_vars[0] == raw_vars[1]
    ):
        raise ValueError("conic_requires_two_variables")
    eliminate_name = args["eliminate"]
    if eliminate_name not in raw_vars:
        raise ValueError("eliminate_must_be_one_of_variables")
    elim_var = p.variable(eliminate_name)
    keep_var = p.variable(raw_vars[0] if raw_vars[1] == eliminate_name else raw_vars[1])

    conic_eqs, conic_ineqs = p.parse_equation_or_relations(args["conic"])
    line_eqs, line_ineqs = p.parse_equation_or_relations(args["line"])
    if len(conic_eqs) != 1 or conic_ineqs or len(line_eqs) != 1 or line_ineqs:
        raise ValueError("conic_and_line_must_be_single_equations")

    line_sol = s.solve(line_eqs[0], elim_var)
    if len(line_sol) != 1:
        raise Unsupported("line_not_linear_in_eliminate_variable")
    sub_expr = line_sol[0]
    combined = s.together(s.expand(conic_eqs[0].subs(elim_var, sub_expr)))
    numer, denom = combined.as_numer_denom()
    out_conditions = set(p.conditions)
    if denom.free_symbols:
        out_conditions.add(f"{denom} != 0")

    poly = s.Poly(s.expand(numer), keep_var)
    deg = poly.degree()
    if deg > 2 or deg < 1:
        raise Unsupported("eliminated_equation_not_quadratic_or_linear")
    if deg == 1:
        c1, c0 = poly.all_coeffs()
        out_conditions.add(f"{c1} != 0")
        payload = {
            "variable": str(keep_var),
            "degree": 1,
            "quadratic_coeff": "0",
            "linear_coeff": str(s.simplify(c1)),
            "constant_coeff": str(s.simplify(c0)),
            "single_root": str(s.simplify(-c0 / c1)),
        }
        return json.dumps(payload, ensure_ascii=False), out_conditions

    a_c, b_c, c_c = poly.all_coeffs()
    if a_c.free_symbols:
        out_conditions.add(f"{s.simplify(a_c)} != 0")
    delta = s.factor(b_c**2 - 4 * a_c * c_c)
    sum_roots = s.simplify(-b_c / a_c)
    prod_roots = s.simplify(c_c / a_c)
    payload = {
        "variable": str(keep_var),
        "degree": 2,
        "quadratic_coeff": str(s.simplify(a_c)),
        "linear_coeff": str(s.simplify(b_c)),
        "constant_coeff": str(s.simplify(c_c)),
        "discriminant": str(delta),
        "sum_roots": str(sum_roots),
        "prod_roots": str(prod_roots),
    }
    return json.dumps(payload, ensure_ascii=False), out_conditions


def _parse_vec3(s, p, raw: str) -> tuple[Any, Any, Any]:
    import ast

    if not isinstance(raw, str) or not 0 < len(raw) <= 256:
        raise ValueError("expected_3d_vector")
    tree = ast.parse(raw, mode="eval")
    if not isinstance(tree.body, (ast.List, ast.Tuple)) or len(tree.body.elts) != 3:
        raise ValueError("expected_3d_vector")
    return tuple(p._visit_expr(raw, elt) for elt in tree.body.elts)


def space_geometry_3d_operation(s, p, args: dict[str, Any]) -> tuple[str, set[str]]:
    from math_executor.engine import Unsupported

    mode = args["mode"]
    out_conditions = set(p.conditions)
    if mode != "plane_metrics":
        raise ValueError("invalid_space_geometry_mode")
    plane_vecs = args.get("plane_vectors")
    if not isinstance(plane_vecs, list) or len(plane_vecs) != 2:
        raise ValueError("plane_requires_two_vectors")
    u = _parse_vec3(s, p, plane_vecs[0])
    v = _parse_vec3(s, p, plane_vecs[1])
    normal = (
        s.simplify(u[1] * v[2] - u[2] * v[1]),
        s.simplify(u[2] * v[0] - u[0] * v[2]),
        s.simplify(u[0] * v[1] - u[1] * v[0]),
    )
    n_norm = s.simplify(s.sqrt(sum(c**2 for c in normal)))
    if n_norm == 0:
        raise ValueError("collinear_plane_vectors")
    if n_norm.free_symbols:
        out_conditions.add(f"{n_norm} != 0")

    result: dict[str, Any] = {
        "normal_vector": f"({normal[0]}, {normal[1]}, {normal[2]})",
        "normal_norm": str(n_norm),
    }

    if "query_vector" in args and args["query_vector"] is not None:
        qv = _parse_vec3(s, p, args["query_vector"])
        q_norm = s.simplify(s.sqrt(sum(c**2 for c in qv)))
        if q_norm == 0:
            raise ValueError("zero_query_vector")
        dot_nv = sum(a * b for a, b in zip(normal, qv))
        sin_theta = s.simplify(s.Abs(dot_nv) / (n_norm * q_norm))
        result["line_plane_sin"] = str(sin_theta)

    if "plane_point" in args and "query_point" in args and args["plane_point"] is not None and args["query_point"] is not None:
        p0 = _parse_vec3(s, p, args["plane_point"])
        qp = _parse_vec3(s, p, args["query_point"])
        diff = tuple(qp[i] - p0[i] for i in range(3))
        dist = s.simplify(s.Abs(sum(normal[i] * diff[i] for i in range(3))) / n_norm)
        result["point_plane_distance"] = str(dist)

    if "second_plane_vectors" in args and args["second_plane_vectors"] is not None:
        sv = args["second_plane_vectors"]
        if not isinstance(sv, list) or len(sv) != 2:
            raise ValueError("second_plane_requires_two_vectors")
        u2 = _parse_vec3(s, p, sv[0])
        v2 = _parse_vec3(s, p, sv[1])
        n2 = (
            s.simplify(u2[1] * v2[2] - u2[2] * v2[1]),
            s.simplify(u2[2] * v2[0] - u2[0] * v2[2]),
            s.simplify(u2[0] * v2[1] - u2[1] * v2[0]),
        )
        n2_norm = s.simplify(s.sqrt(sum(c**2 for c in n2)))
        if n2_norm == 0:
            raise Unsupported("collinear_second_plane_vectors")
        cos_abs = s.simplify(s.Abs(sum(normal[i] * n2[i] for i in range(3))) / (n_norm * n2_norm))
        result["dihedral_cos_abs"] = str(cos_abs)

    return json.dumps(result, ensure_ascii=False), out_conditions
