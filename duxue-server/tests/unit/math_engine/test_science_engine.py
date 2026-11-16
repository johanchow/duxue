import json

from math_executor.engine import execute


def run(op: str, args: dict, **extra) -> dict:
    return execute({"op": op, "args": args, "symbols": [], "assumptions": [], **extra})


def test_algebra_transform_and_summation():
    symbols = [
        {"name": "x", "domain": "real"},
        {"name": "a", "domain": "real"},
        {"name": "n", "domain": "integer"},
        {"name": "k", "domain": "integer"},
    ]
    factored = run(
        "transform",
        {"expression": "-(2*a*x**2 - (2*a+1)*x + 1)/x", "mode": "factor"},
        symbols=symbols,
    )
    assert factored["status"] == "ok"
    assert "(x - 1)" in factored["result"]
    assert "(2*a*x - 1)" in factored["result"]

    trig = run(
        "transform",
        {"expression": "sin(x)**2 + cos(x)**2 + 2*sin(x)*cos(x) - 1", "mode": "trigsimp"},
        symbols=symbols,
    )
    assert trig["status"] == "ok"
    assert trig["result"] == "sin(2*x)"

    finite_sum = run(
        "summation",
        {"expression": "1/(k*(k+1))", "variable": "k", "start": "1", "end": "n"},
        symbols=symbols,
        assumptions=["n:positive"],
    )
    assert finite_sum["status"] == "ok"
    # 1 - 1/(n+1) == n/(n+1)
    eq = run(
        "equivalent",
        {"left": finite_sum["result"], "right": "n/(n+1)"},
        symbols=symbols,
        assumptions=["n:positive"],
    )
    assert eq["verdict"] == "equal"

    # Reject unbounded numeric summation span
    too_wide = run(
        "summation",
        {"expression": "k", "variable": "k", "start": "1", "end": "100000000"},
        symbols=symbols,
    )
    assert too_wide["status"] != "ok"


def test_analyze_function_monotonicity_and_extrema():
    res = run(
        "analyze_function",
        {"expression": "x**3 - 3*x", "variable": "x", "domain_interval": "(-oo, oo)"},
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert res["status"] == "ok"
    data = json.loads(res["result"])
    assert data["derivative"] in {"3*x**2 - 3", "3*(x - 1)*(x + 1)"}
    assert data["critical_points"] == ["-1", "1"]
    signs = [(iv["interval"], iv["sign"]) for iv in data["intervals"]]
    assert signs == [("(-oo, -1)", "+"), ("(-1, 1)", "-"), ("(1, oo)", "+")]

    log_fn = run(
        "analyze_function",
        {"expression": "ln(x) - x", "variable": "x", "domain_interval": "(0, oo)"},
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert log_fn["status"] == "ok"
    log_data = json.loads(log_fn["result"])
    assert log_data["critical_points"] == ["1"]
    assert [(iv["interval"], iv["sign"]) for iv in log_data["intervals"]] == [
        ("(0, 1)", "+"),
        ("(1, oo)", "-"),
    ]


def test_search_counterexample_refutes_false_parameter_bound_and_never_proves_true():
    symbols = [{"name": "x", "domain": "real"}, {"name": "a", "domain": "real"}]
    # ln(x) <= a*x - 1 on x > 0 holds iff a >= 1 (at x=1, 0 <= a-1 => a>=1; for a=2, at x=0.1: ln(0.1)=-2.302 <= -0.8 true, wait: at a=2, f(x)=ln(x)-2x+1, max at x=1/2 is ln(1/2)-1+1 = -ln(2) < 0, wait at x=0.1, a=0.5: ln(10)=2.302 > 0.5*10-1=4? At x=10, a=0.5: ln(10)=2.30, 0.5*10-1=4 (holds), at x=1, a=0.5: 0 <= -0.5 FALSE!)
    refuted = run(
        "search_counterexample",
        {
            "relation": "ln(x) <= a*x - 1",
            "bounds": {"x": [0.05, 10.0], "a": [0.2, 2.0]},
        },
        symbols=symbols,
    )
    # Disproved => status="ok",checked_scope="equivalence", verdict="not_equal"
    assert refuted["status"] == "ok"
    assert refuted["verdict"] == "not_equal"
    witness = json.loads(refuted["result"])
    assert witness["counterexample_found"] is True
    assert "x" in witness["point"] and "a" in witness["point"]

    # True statement: ln(x) <= x - 1 on x in [0.05, 10] -> no counterexample -> MUST be unknown, NEVER equal!
    not_refuted = run(
        "search_counterexample",
        {
            "relation": "ln(x) <= x - 1",
            "bounds": {"x": [0.05, 10.0]},
        },
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert not_refuted["status"] == "unknown"
    assert not_refuted.get("verdict") == "unknown"


def test_conic_line_vieta_and_space_geometry_3d():
    symbols = [
        {"name": "x", "domain": "real"},
        {"name": "y", "domain": "real"},
        {"name": "k", "domain": "real"},
        {"name": "m", "domain": "real"},
    ]
    vieta = run(
        "conic_line_system",
        {
            "conic": "x**2/4 + y**2/3 - 1",
            "line": "y - (k*x + m)",
            "variables": ["x", "y"],
            "eliminate": "y",
        },
        symbols=symbols,
    )
    assert vieta["status"] == "ok"
    payload = json.loads(vieta["result"])
    # (3 + 4k^2)x^2 + 8km x + 4m^2 - 12 = 0
    assert run(
        "equivalent",
        {"left": payload["sum_roots"], "right": "-8*k*m/(4*k**2 + 3)"},
        symbols=symbols,
    )["verdict"] == "equal"
    assert run(
        "equivalent",
        {"left": payload["prod_roots"], "right": "(4*m**2 - 12)/(4*k**2 + 3)"},
        symbols=symbols,
    )["verdict"] == "equal"
    assert run(
        "equivalent",
        {"left": payload["discriminant"], "right": "48*(4*k**2 - m**2 + 3)"},
        symbols=symbols,
    )["verdict"] == "equal"

    geom = run(
        "space_geometry_3d",
        {
            "mode": "plane_metrics",
            "plane_vectors": ["[1, 0, 1]", "[0, 1, 1]"],
            "plane_point": "[0, 0, 0]",
            "query_vector": "[0, 0, 1]",
            "query_point": "[1, 1, 1]",
        },
    )
    assert geom["status"] == "ok"
    gdata = json.loads(geom["result"])
    # Normal to (1,0,1) and (0,1,1) is (-1, -1, 1) -> norm sqrt(3)
    # sin(line, plane) = |n . v| / (|n||v|) = 1/sqrt(3) = sqrt(3)/3
    assert gdata["line_plane_sin"] == "sqrt(3)/3"
    # distance from (1,1,1) to -x - y + z = 0 is |-1 - 1 + 1|/sqrt(3) = sqrt(3)/3
    assert gdata["point_plane_distance"] == "sqrt(3)/3"


def test_probability_distribution_regression_and_chi2():
    dist = run(
        "probability_stats",
        {
            "mode": "discrete_distribution",
            "values": ["0", "1", "2"],
            "probabilities": ["1/6", "1/2", "1/3"],
        },
    )
    assert dist["status"] == "ok"
    d = json.loads(dist["result"])
    assert d["valid_distribution"] is True
    assert d["expectation"] == "7/6"
    # E(X^2) = 0 + 1/2 + 4/3 = 11/6; Var = 11/6 - 49/36 = (66-49)/36 = 17/36
    assert d["variance"] == "17/36"

    bad_dist = run(
        "probability_stats",
        {
            "mode": "discrete_distribution",
            "values": ["0", "1"],
            "probabilities": ["1/3", "1/3"],
        },
    )
    assert bad_dist["status"] == "ok"
    assert json.loads(bad_dist["result"])["valid_distribution"] is False

    chi = run(
        "probability_stats",
        {
            "mode": "chi2_2x2",
            "table": [[40, 10], [20, 30]],
        },
    )
    assert chi["status"] == "ok"
    cdata = json.loads(chi["result"])
    # n=100, ad-bc = 1200-200 = 1000, K^2 = 100 * 1000^2 / (50*50*60*40) = 100_000_000 / 6_000_000 = 50/3
    assert cdata["chi2_exact"] == "50/3"
    assert cdata["exceeds_6_635"] is True
    assert cdata["exceeds_10_828"] is True

    reg = run(
        "probability_stats",
        {
            "mode": "linear_regression",
            "x": ["1", "2", "3", "4", "5"],
            "y": ["2", "4", "5", "4", "5"],
        },
    )
    assert reg["status"] == "ok"
    rdata = json.loads(reg["result"])
    assert rdata["slope"] == "3/5"
    assert rdata["intercept"] == "11/5"


def test_physics_dimensions_consistency():
    # T == 2*pi*sqrt(L/g) -> both [T^1]
    pendulum = run(
        "check_dimensions",
        {
            "left": "T",
            "right": "2*pi*sqrt(L/g)",
            "quantities": {"T": "T", "L": "L", "g": "L*T**-2"},
        },
    )
    assert pendulum["status"] == "ok"
    assert pendulum["verdict"] == "equal"

    # Lorentz radius r = m*v/(q*B): F = q*v*B => B has dim M*L*T^-2 / (I*T * L*T^-1) = M*T^-2*I^-1
    # m*v/(q*B) = M*(L*T^-1) / ((I*T)*(M*T^-2*I^-1)) = L
    cyclotron = run(
        "check_dimensions",
        {
            "left": "r",
            "right": "m*v/(q*B)",
            "quantities": {
                "r": "L",
                "m": "M",
                "v": "L*T**-1",
                "q": "I*T",
                "B": "M*T**-2*I**-1",
            },
        },
    )
    assert cyclotron["status"] == "ok"
    assert cyclotron["verdict"] == "equal"

    # Dimension mismatch in addition: v + a*t**2
    bad_add = run(
        "check_dimensions",
        {
            "left": "x",
            "right": "v + a*t**2/2",
            "quantities": {"x": "L", "v": "L*T**-1", "a": "L*T**-2", "t": "T"},
        },
    )
    assert bad_add["status"] == "ok"
    assert bad_add["verdict"] == "not_equal"

    # Non-dimensionless inside sin(v*t) where v*t has dim L
    bad_trig = run(
        "check_dimensions",
        {
            "left": "1",
            "right": "sin(v*t)",
            "quantities": {"v": "L*T**-1", "t": "T"},
        },
    )
    assert bad_trig["status"] == "ok"
    assert bad_trig["verdict"] == "not_equal"


def test_chemistry_reaction_atom_and_charge_conservation():
    # Balanced ionic redox: Cr2O7^2- + 6 Fe^2+ + 14 H^+ -> 2 Cr^3+ + 6 Fe^3+ + 7 H2O
    good = run(
        "check_reaction",
        {
            "equation": "Cr2O7^2- + 6 Fe^2+ + 14 H^+ -> 2 Cr^3+ + 6 Fe^3+ + 7 H2O",
        },
    )
    assert good["status"] == "ok"
    assert good["verdict"] == "equal"
    g_info = json.loads(good["result"])
    assert g_info["atom_conserved"] is True
    assert g_info["charge_conserved"] is True

    # Classic student mistake: Fe + 2 Fe^3+ -> 3 Fe^2+ vs wrong charge Fe + Fe^3+ -> 2 Fe^2+
    bad_charge = run(
        "check_reaction",
        {
            "equation": "Fe + Fe^3+ -> 2 Fe^2+",
        },
    )
    assert bad_charge["status"] == "ok"
    assert bad_charge["verdict"] == "not_equal"
    b_info = json.loads(bad_charge["result"])
    assert b_info["atom_conserved"] is True
    assert b_info["charge_conserved"] is False

    # Coordination complex & crystal hydrate: [Ag(NH3)2]^+ + OH^- + 2 H^+ -> Ag^+ + 2 NH4^+ + OH^-
    complex_eq = run(
        "check_reaction",
        {
            "equation": "[Ag(NH3)2]^+ + 2 H^+ -> Ag^+ + 2 NH4^+",
        },
    )
    assert complex_eq["status"] == "ok"
    assert complex_eq["verdict"] == "equal"


def test_biology_genetics_cross_autosomal_sex_linked_and_lethal():
    # Classic dihybrid AaBb x AaBb with AA lethal -> viable offspring: (2 Aa : 1 aa) x (3 B_ : 1 bb) => 6:2:3:1
    lethal = run(
        "genetics_cross",
        {
            "parent1": ["Aa", "Bb"],
            "parent2": ["Aa", "Bb"],
            "lethal_genotypes": ["AA"],
        },
    )
    assert lethal["status"] == "ok"
    ldata = json.loads(lethal["result"])
    assert ldata["phenotype_ratios"] == {
        "A_B_": "1/2",
        "A_bb": "1/6",
        "aaB_": "1/4",
        "aabb": "1/12",
    }

    # Sex-linked X^A X^a x X^a Y
    sex_linked = run(
        "genetics_cross",
        {
            "parent1": ["X^AX^a"],
            "parent2": ["X^aY"],
        },
    )
    assert sex_linked["status"] == "ok"
    sdata = json.loads(sex_linked["result"])
    assert sdata["genotype_ratios"] == {
        "X^AX^a": "1/4",
        "X^AY": "1/4",
        "X^aX^a": "1/4",
        "X^aY": "1/4",
    }
