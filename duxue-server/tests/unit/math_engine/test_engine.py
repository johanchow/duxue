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
