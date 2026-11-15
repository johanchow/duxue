import pytest

from math_executor.engine import execute


def run(op, args, **extra):
    return execute({"op": op, "args": args, "symbols": [], "assumptions": [], **extra})


def test_exact_arithmetic():
    assert run("evaluate", {"expression": "0.1+0.2"})["result"] == "3/10"
    assert run("equivalent", {"left": "90-37", "right": "53"})["verdict"] == "equal"
    assert (
        run("equivalent", {"left": "34-(28-13)", "right": "17"})["verdict"]
        == "not_equal"
    )


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os")',
        "x.__class__",
        "[1]*100",
        "lambda:1",
        "2**9999999",
        "1/0",
        "sin",
        "True",
        "1e999999",
        "x[0]",
    ],
)
def test_reject_unsafe_or_unbounded_expressions(expression):
    assert run("evaluate", {"expression": expression})["status"] != "ok"


def test_symbolic_operations_and_domains():
    symbols = [{"name": "x", "domain": "real"}]
    assert (
        run(
            "differentiate",
            {"expression": "x**2", "variable": "x", "order": 1},
            symbols=symbols,
        )["result"]
        == "2*x"
    )
    assert (
        run(
            "integrate",
            {"expression": "x", "variable": "x", "bounds": ["0", "2"]},
            symbols=symbols,
        )["result"]
        == "2"
    )
    assert (
        run(
            "limit",
            {"expression": "sin(x)/x", "variable": "x", "point": "0", "direction": "+"},
            symbols=symbols,
        )["result"]
        == "1"
    )
    assert (
        run("solve", {"equations": ["x**2-1"], "variables": ["x"]}, symbols=symbols)[
            "result"
        ]
        == "{-1, 1}"
    )
    # These are NOT identities on the whole stated domain.
    assert (
        run("equivalent", {"left": "sqrt(x**2)", "right": "x"}, symbols=symbols)[
            "verdict"
        ]
        != "equal"
    )
    assert (
        run("equivalent", {"left": "x/x", "right": "1"}, symbols=symbols)["verdict"]
        == "unknown"
    )
    assert (
        run(
            "equivalent",
            {"left": "x/x", "right": "1"},
            symbols=symbols,
            assumptions=["x:nonzero"],
        )["verdict"]
        == "equal"
    )


def test_unknown_does_not_mean_wrong():
    r = run(
        "solve",
        {"equations": ["sin(x)-x/2"], "variables": ["x"]},
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert r["status"] == "unknown"
    assert r.get("verdict") != "not_equal"


def test_high_school_complex_numbers_and_fractional_symbolic_powers():
    assert run("evaluate", {"expression": "(1+3*I)/(1-I)"})["result"] == "-1 + 2*I"
    assert (
        run("equivalent", {"left": "(1+3*I)/(1-I)", "right": "-1+2*I"})["verdict"]
        == "equal"
    )
    assert run("evaluate", {"expression": "abs((1+I)**2 - 2*(1+I))"})["result"] == "2"
    assert run("evaluate", {"expression": "8**(1/3)"})["result"] == "2"
    assert run("evaluate", {"expression": "cbrt(-8)"})["result"] == "-2"
    assert run("evaluate", {"expression": "10**(-1/10)", "precision": 3})["result"].startswith("0.79")
    assert run("evaluate", {"expression": "(-4)**(1/2)"})["status"] != "ok"
    seq = run(
        "equivalent",
        {"left": "2**(2*n-1) * 4", "right": "2**(2*(n+1)-1)"},
        symbols=[{"name": "n", "domain": "integer"}],
    )
    assert seq["verdict"] == "equal"


def test_high_school_functions_combinatorics_and_vectors():
    assert run("evaluate", {"expression": "log(8, 2)"})["result"] == "3"
    assert run("evaluate", {"expression": "ln(E**3)"})["result"] == "3"
    assert run("evaluate", {"expression": "cot(pi/4)"})["result"] == "1"
    assert run("evaluate", {"expression": "asin(1/2)"})["result"] == "pi/6"
    assert run("evaluate", {"expression": "asin(2)"})["status"] != "ok"
    assert run("evaluate", {"expression": "binomial(5, 3)"})["result"] == "10"
    assert run("evaluate", {"expression": "factorial(5)"})["result"] == "120"
    assert run("evaluate", {"expression": "factorial(500)"})["status"] != "ok"
    assert run("evaluate", {"expression": "binomial(100000, 50000)"})["status"] != "ok"
    assert run("evaluate", {"expression": "dot([-2, 3], [3, 2])"})["result"] == "0"
    assert run("evaluate", {"expression": "norm([3, 4])"})["result"] == "5"
    assert (
        run("evaluate", {"expression": "cross([1, 0, 0], [0, 1, 0])"})["result"]
        == "(0, 0, 1)"
    )
    assert run("evaluate", {"expression": "[1, 2] + [3, 4]"})["status"] != "ok"


def test_high_school_multivariate_systems_parameterized_and_inequalities():
    ap = run(
        "solve",
        {"equations": ["a1 + 9*d = -9", "a1 + 2*d = 5"], "variables": ["a1", "d"]},
        symbols=[{"name": "a1", "domain": "real"}, {"name": "d", "domain": "real"}],
    )
    assert ap["status"] == "ok"
    assert ap["result"] == "{{a1: 9, d: -2}}"

    circles = run(
        "solve",
        {
            "equations": ["x**2 + y**2 - 2*y", "x**2 + y**2 - 2*sqrt(3)*x"],
            "variables": ["x", "y"],
        },
        symbols=[{"name": "x", "domain": "real"}, {"name": "y", "domain": "real"}],
    )
    assert circles["status"] == "ok"
    assert "{x: 0, y: 0}" in circles["result"]
    assert "{x: sqrt(3)/2, y: 3/2}" in circles["result"]

    collision = run(
        "solve",
        {
            "equations": [
                "mA*v0 - mB*v0 = mA*vA + mB*vB",
                "mA*v0**2 + mB*v0**2 = mA*vA**2 + mB*vB**2",
            ],
            "variables": ["vA", "vB"],
        },
        symbols=[
            {"name": "mA", "domain": "real"},
            {"name": "mB", "domain": "real"},
            {"name": "v0", "domain": "real"},
            {"name": "vA", "domain": "real"},
            {"name": "vB", "domain": "real"},
        ],
        assumptions=["mA:positive", "mB:positive", "v0:positive"],
    )
    assert collision["status"] == "ok"
    assert "(3*mA - mB)" in collision["result"] or "3*mA*v0/(mA + mB)" in collision["result"]

    extraneous = run(
        "solve",
        {"equations": ["(x**2 - 1)/(x - 1) = 0"], "variables": ["x"]},
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert extraneous["status"] == "ok"
    assert extraneous["result"] == "{-1}"

    hyperbola = run(
        "solve",
        {"equations": ["(n + 1)*(3 - n) > 0"], "variables": ["n"]},
        symbols=[{"name": "n", "domain": "real"}],
    )
    assert hyperbola["status"] == "ok"
    assert "-1 < n" in hyperbola["result"] and "n < 3" in hyperbola["result"]

    rational_ineq = run(
        "solve",
        {"equations": ["1/(x - 1) > 1"], "variables": ["x"]},
        symbols=[{"name": "x", "domain": "real"}],
    )
    assert rational_ineq["status"] == "ok"
    assert "1 < x" in rational_ineq["result"] and "x < 2" in rational_ineq["result"]
