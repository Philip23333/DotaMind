import asyncio

import pytest

from app.vnext.llm.protocol import ToolCall
from app.vnext.tools.calculate import register_calculate_tool
from app.vnext.tools.registry import ToolRegistry


def calculate(expression, variables=None, **kwargs):
    registry = ToolRegistry()
    register_calculate_tool(registry)
    return asyncio.run(
        registry.execute(
            ToolCall(
                id="calculate",
                name="math.calculate",
                arguments={"expression": expression, "variables": variables or {}, **kwargs},
            )
        )
    )


@pytest.mark.parametrize(
    ("expression", "variables", "expected"),
    [
        ("a-b", {"a": 1478, "b": 1010}, 468),
        ("0.1 + 0.2", {}, 0.3),
        ("(a+b)/2", {"a": 3, "b": 4}, 3.5),
        ("sum(values)", {"values": [1, 2, 3]}, 6),
        ("mean([1, 2, 3, 4])", {}, 2.5),
        ("min([-3, 2]) + max([1, 2])", {}, -1),
        ("+a * -b", {"a": 3, "b": 2}, -6),
        ("1e3 / 4", {}, 250),
        ("1 / 3", {}, 0.3333),
        ("1.23445", {}, 1.2345),
        ("-1.23445", {}, -1.2345),
        ("-0.00001", {}, 0),
    ],
)
def test_arithmetic(expression, variables, expected):
    response = calculate(expression, variables)
    assert response.status == "ok", response
    assert response.content["result"] == expected
    assert response.content["label"] is None
    assert response.content["result_unit"] is None


def test_time_difference_and_echo():
    result = calculate("a - b", {"a": 1478, "b": 1010}, result_unit="seconds").content
    assert result == {
        "expression": "a - b",
        "variables": {"a": 1478, "b": 1010},
        "result": 468,
        "result_unit": "seconds",
        "label": "07:48",
        "equation": "(1478 - 1010) = 468",
        "rounded": False,
    }
    assert calculate("-0.5", result_unit="seconds").content["label"] == "-00:00.5"
    assert calculate("1 / 3", result_unit="seconds").content["label"] == "00:00.3333"


def test_equation_keeps_parentheses_and_approximation():
    result = calculate("(a + b) / 3", {"a": 1, "b": 0}).content
    assert result["equation"] == "((1 + 0) / 3) ≈ 0.3333"
    assert result["rounded"] is True
    result = calculate("0.1 + 0.2").content
    assert result["rounded"] is False
    assert result["equation"].endswith("= 0.3")


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        "3",
        [1, None],
        [True],
        ["1"],
        [],
        {},
        {"ref": "artifact:tool:abc"},
        float("nan"),
        float("inf"),
    ],
)
def test_rejects_missing_coerced_or_reference_inputs(value):
    result = calculate("a", {"a": value})
    assert result.status == "error"
    assert result.error.code == "invalid_arguments"
    assert any("a" in item["loc"] for item in result.error.details["validation_errors"])


@pytest.mark.parametrize(
    "expression",
    [
        "1 / 0",
        "missing + 1",
        "2**3",
        "3 % 2",
        "3 // 2",
        "1 < 2",
        "1 and 2",
        "1 if True else 2",
        "'x'",
        "True",
        "None",
        "a[0]",
        "a.real",
        "[x for x in a]",
        "sum(*a)",
        "sum(a, start=0)",
        "abs(-1)",
        "__import__('os')",
        "(1, 2)",
        "[1, 2]",
        "sum([[1]])",
        "sum([])",
        "sum(1)",
        "1 + [2]",
        "[1] * 100",
        "lambda: 1",
        "0xff",
        "1_000",
        "1e999999999",
        "1e-999999999",
        "a = 1",
        "(",
    ],
)
def test_denies_non_whitelisted_syntax(expression):
    result = calculate(expression, {"a": [1, 2]})
    assert result.status == "error", result
    assert result.error.code == "invalid_arguments"


@pytest.mark.parametrize(
    ("expression", "variables"),
    [
        ("1" * 1025, {}),
        ("1e16", {}),
        ("1e15 * 2", {}),
        ("a", {"a": 10**16}),
        ("a", {"a": [1] * 101}),
        ("a", {f"v{i}": 1 for i in range(33)}),
        ("a", {"sum": 1}),
        ("a", {"_private": 1}),
        ("a", {"a": [1] * 100, "b": [1] * 100, "c": [1] * 100}),
        ("+" * 34 + "1", {}),
        ("+".join(["1"] * 100), {}),
    ],
)
def test_bounds(expression, variables):
    assert calculate(expression, variables).status == "error"


def test_no_unit_inference_or_other_units():
    assert calculate("468").content["label"] is None
    assert calculate("468", result_unit="minutes").status == "error"


def test_large_integer_stays_exact_and_fraction_cannot_silently_change():
    assert calculate("1000000000000000").content["result"] == 1000000000000000
    result = calculate("999999999999999.9999")
    assert result.status == "error"
    assert "JSON numeric precision" in result.error.message
