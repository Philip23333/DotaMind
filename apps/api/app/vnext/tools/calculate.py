"""Bounded decimal arithmetic; no Python execution or source-data access."""

from __future__ import annotations

import ast
import re
from decimal import ROUND_HALF_UP, Decimal, DecimalException, Inexact, localcontext
from typing import Annotated, Literal

from pydantic import Field, StrictFloat, StrictInt, field_validator, model_validator

from app.vnext.domain.common.models import DomainModel
from app.vnext.domain.common.time_format import format_game_time
from app.vnext.tools.definition import ToolAccess, ToolDefinition
from app.vnext.tools.errors import StructuredToolError
from app.vnext.tools.registry import ToolRegistry

Number = Annotated[StrictInt | StrictFloat, Field(ge=-(10**15), le=10**15, allow_inf_nan=False)]
NumberList = Annotated[list[Number], Field(min_length=1, max_length=100)]
_FUNCTIONS = {"sum", "mean", "min", "max"}
_NUMBER = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


class CalculateInput(DomainModel):
    expression: str = Field(min_length=1, max_length=1024)
    variables: dict[str, Number | NumberList] = Field(default_factory=dict, max_length=32)
    result_unit: Literal["seconds"] | None = None

    @field_validator("variables")
    @classmethod
    def validate_names(cls, values: dict) -> dict:
        for name in values:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", name) or name in _FUNCTIONS:
                raise ValueError(f"invalid variable name: {name}")
        return values

    @model_validator(mode="after")
    def bound_values(self) -> CalculateInput:
        if sum(len(v) if isinstance(v, list) else 1 for v in self.variables.values()) > 256:
            raise ValueError("at most 256 variable numbers are allowed")
        return self


class CalculateResult(DomainModel):
    expression: str
    variables: dict[str, Number | NumberList]
    result: Number
    result_unit: Literal["seconds"] | None
    label: str | None
    equation: str
    rounded: bool


def _invalid(message: str) -> StructuredToolError:
    return StructuredToolError("invalid_arguments", message)


def _text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".") if value % 1 else format(value, ".0f")


class _Evaluator:
    def __init__(self, args: CalculateInput) -> None:
        self.args = args
        self.expression = args.expression.strip()

    @staticmethod
    def bound(value: Decimal) -> Decimal:
        if not value.is_finite() or value.copy_abs() > 10**15:
            raise _invalid("number or intermediate result exceeds the finite ±10^15 bound")
        if value and value.adjusted() < -100:
            raise _invalid("number or intermediate result is smaller than 1e-100")
        return value

    def evaluate(self, node: ast.AST, depth: int = 0) -> tuple[Decimal | list[Decimal], str]:
        if depth > 32:
            raise _invalid("expression nesting exceeds 32")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            token = ast.get_source_segment(self.expression, node) or ""
            if len(token) > 64 or not _NUMBER.fullmatch(token):
                raise _invalid(
                    "only decimal numeric constants of at most 64 characters are allowed"
                )
            value = self.bound(Decimal(token))
            return value, _text(value)
        if isinstance(node, ast.Name):
            if node.id not in self.args.variables:
                raise _invalid(f"unknown variable: {node.id}")
            raw = self.args.variables[node.id]
            if isinstance(raw, list):
                values = [self.bound(Decimal(str(v))) for v in raw]
                return values, "[" + ", ".join(_text(v) for v in values) + "]"
            value = self.bound(Decimal(str(raw)))
            return value, _text(value)
        if isinstance(node, ast.List):
            if not 1 <= len(node.elts) <= 100:
                raise _invalid("lists must contain 1 to 100 numbers")
            evaluated = [self.evaluate(item, depth + 1) for item in node.elts]
            if any(not isinstance(value, Decimal) for value, _ in evaluated):
                raise _invalid("nested lists are not allowed")
            return [value for value, _ in evaluated], "[" + ", ".join(s for _, s in evaluated) + "]"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value, text = self.evaluate(node.operand, depth + 1)
            if not isinstance(value, Decimal):
                raise _invalid("unary arithmetic requires a number")
            negative = isinstance(node.op, ast.USub)
            return self.bound(-value if negative else value), f"({'-' if negative else '+'}{text})"
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left, left_text = self.evaluate(node.left, depth + 1)
            right, right_text = self.evaluate(node.right, depth + 1)
            if not isinstance(left, Decimal) or not isinstance(right, Decimal):
                raise _invalid("arithmetic operands must be numbers; use an aggregate for a list")
            if isinstance(node.op, ast.Add):
                value, op = left + right, "+"
            elif isinstance(node.op, ast.Sub):
                value, op = left - right, "-"
            elif isinstance(node.op, ast.Mult):
                value, op = left * right, "*"
            else:
                if right == 0:
                    raise _invalid("division by zero")
                value, op = left / right, "/"
            text = f"({left_text} {op} {right_text})"
            if len(text) > 8192:
                raise _invalid("substituted equation exceeds 8192 characters")
            return self.bound(value), text
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCTIONS
            and len(node.args) == 1
            and not node.keywords
        ):
            values, text = self.evaluate(node.args[0], depth + 1)
            if not isinstance(values, list):
                raise _invalid("sum, mean, min and max each require one nonempty numeric list")
            name = node.func.id
            if name in {"sum", "mean"}:
                value = Decimal(0)
                for item in values:
                    value = self.bound(value + item)
                if name == "mean":
                    value /= len(values)
            else:
                value = min(values) if name == "min" else max(values)
            return self.bound(value), f"{name}({text})"
        raise _invalid(f"unsupported expression element: {type(node).__name__}")

    def run(self) -> CalculateResult:
        try:
            tree = ast.parse(self.expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 256:
                raise _invalid("expression exceeds 256 syntax nodes")
            with localcontext() as context:
                context.prec = 28
                context.rounding = ROUND_HALF_UP
                context.clear_flags()
                value, substituted = self.evaluate(tree.body)
                if not isinstance(value, Decimal):
                    raise _invalid("the final result must be a number")
                if len(substituted) > 8192:
                    raise _invalid("substituted equation exceeds 8192 characters")
                value = value.quantize(Decimal("0.0001"))
                rounded = context.flags[Inexact]
                text = _text(value)
                result = int(value) if value == value.to_integral_value() else float(text)
                if Decimal(str(result)) != value:
                    raise _invalid("result exceeds the supported JSON numeric precision")
                return CalculateResult(
                    expression=self.args.expression,
                    variables=self.args.variables,
                    result=result,
                    result_unit=self.args.result_unit,
                    label=format_game_time(result) if self.args.result_unit == "seconds" else None,
                    equation=f"{substituted} {'≈' if rounded else '='} {text}",
                    rounded=rounded,
                )
        except (SyntaxError, ValueError, RecursionError, DecimalException) as exc:
            raise _invalid("invalid or out-of-bounds decimal expression") from exc


def register_calculate_tool(registry: ToolRegistry) -> None:
    registry.register(
        ToolDefinition(
            name="math.calculate",
            description=(
                "Calculate temporary numeric results from verified inputs. Use +, -, *, /, "
                "parentheses, unary signs, or sum/mean/min/max with one nonempty numeric list. "
                "Variables accept finite numbers or numeric lists; reject null, bool and strings. "
                "No powers, modulo, indexing, attributes, Python code, or Artifact references. "
                "Results use at most four decimal places, half-up rounding. "
                "Set result_unit='seconds' for a time label. Copy result/equation/label; "
                "do not recalculate mentally. "
                "The tool verifies arithmetic, not source selection or units. Limits: expression "
                "1024 characters, 32 variables, 256 variable numbers, lists of 1–100, nesting 32, "
                "256 syntax nodes, numeric magnitudes at most 10^15 and nonzero at least 1e-100."
            ),
            input_model=CalculateInput,
            output_model=CalculateResult,
            handler=lambda args: _Evaluator(args).run(),
            access=ToolAccess.PURE_COMPUTE,
            externalize_result=False,
            parallel_safe=True,
        )
    )
