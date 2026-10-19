"""Bounded JSONPath selection and faithful direct-field projection."""

from __future__ import annotations

import asyncio
import math
from itertools import islice
from typing import Any

from jsonpath import JSONPathEnvironment
from jsonpath.exceptions import JSONPathError
from jsonpath.filter import (
    BooleanLiteral,
    FloatLiteral,
    InfixExpression,
    IntegerLiteral,
    Nil,
    RelativeFilterQuery,
    StringLiteral,
)
from jsonpath.path import JSONPath
from jsonpath.segments import JSONPathChildSegment
from jsonpath.selectors import Filter, IndexSelector, NameSelector, WildcardSelector
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from .externalize import serialized_size
from .limits import DEFAULT_ARTIFACT_LIMITS
from .retrieval import ArtifactReadValidationError
from .store import SessionArtifactStore


class ArtifactQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: StrictStr = Field(description="Exact existing session Artifact reference.")
    expression: StrictStr = Field(
        min_length=1,
        max_length=1024,
        description="Restricted JSONPath: named members, nonnegative indexes, array [*], "
        "and optional [?@.field == literal] filters with comparisons, &&, || and parentheses. "
        "Use $.rows[*] to project object records without a filter.",
    )
    fields: list[StrictStr] = Field(
        min_length=1,
        max_length=16,
        description="Distinct literal direct member names, including identity/time/labels "
        "needed for verification. Use observed record fields; inspect a sample with read "
        "when unknown. No aliases, nested projection or inferred parent fields.",
    )
    offset: int = Field(
        default=0,
        ge=0,
        le=10_000,
        strict=True,
        description="Offset in matches after filtering; not a timestamp or source-array index.",
    )
    limit: int = Field(default=20, ge=1, le=100, strict=True)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        if any(not field for field in value) or len(set(value)) != len(value):
            raise ValueError("fields must be distinct nonempty direct member names")
        return value


class ArtifactQueryMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    value: dict[str, Any]
    missing_fields: list[str]


class ArtifactQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    expression: str
    fields: list[str]
    matches: list[ArtifactQueryMatch]
    offset: int
    limit: int
    returned: int
    next_offset: int | None
    truncated: bool


class QueryBudgetExceeded(Exception):
    """Evaluation stopped before exceeding its per-query work budget."""

    def __init__(self, limit: int, used: int):
        super().__init__("query evaluation work limit exceeded; narrow the selected path or range")
        self.limit = limit
        self.used = used


class QueryFieldsUnavailable(ArtifactReadValidationError):
    """Requested fields absent from every record admitted to this page."""

    def __init__(self, missing_fields: list[str], sample_path: str, sample: dict):
        super().__init__(
            "Requested fields do not occur in this page's matched records; "
            "inspect the sample's available fields and retry. "
            "This does not establish absence from other records or business facts."
        )
        keys = list(islice(sample, 65))
        self.details = {
            "missing_fields": missing_fields,
            "sample_path": sample_path,
            "available_fields": keys[:64],
            "available_fields_truncated": len(keys) > 64,
        }


class _QueryEnvironment(JSONPathEnvironment):
    def __init__(self, max_work: int):
        super().__init__(strict=True, filter_caching=False)
        self.max_work = max_work
        self.used_work = 0

    def charge(self) -> None:
        if self.used_work >= self.max_work:
            raise QueryBudgetExceeded(self.max_work, self.used_work)
        self.used_work += 1

    def getitem(self, obj, key):
        # Charge attempts too, including missing fields and indexes.
        self.charge()
        return super().getitem(obj, key)

    def compare(self, left, operator, right):
        # Every allowed filter requires comparisons, even with no matches.
        self.charge()
        return super().compare(left, operator, right)


class _ArrayWildcard(WildcardSelector):
    def resolve(self, node):
        if isinstance(node.obj, dict):
            raise ArtifactReadValidationError("wildcard traversal is allowed only on arrays")
        for match in super().resolve(node):
            self.env.charge()
            yield match


class _ArrayFilter(Filter):
    def resolve(self, node):
        if isinstance(node.obj, dict):
            raise ArtifactReadValidationError("filters are allowed only on arrays")
        yield from super().resolve(node)


def _compile(expression: str, max_work: int) -> JSONPath:
    env = _QueryEnvironment(max_work)
    path = env.compile(expression)
    comparisons = 0

    def check_condition(node, depth=0):
        nonlocal comparisons
        if type(node) is not InfixExpression:
            raise ArtifactReadValidationError("filter requires relative-path/scalar comparisons")
        if node.operator in {"&&", "||"}:
            if depth >= 8:
                raise ArtifactReadValidationError("logical nesting exceeds 8")
            check_condition(node.left, depth + 1)
            check_condition(node.right, depth + 1)
            return
        comparisons += 1
        if comparisons > 32:
            raise ArtifactReadValidationError("query exceeds 32 comparisons")
        if (
            node.operator not in {"==", "!=", "<", "<=", ">", ">="}
            or type(node.left) is not RelativeFilterQuery
            or type(node.right)
            not in {
                BooleanLiteral,
                FloatLiteral,
                IntegerLiteral,
                StringLiteral,
                Nil,
            }
        ):
            raise ArtifactReadValidationError("only relative-path/scalar comparisons are supported")
        if type(node.right) is FloatLiteral and not math.isfinite(node.right.value):
            raise ArtifactReadValidationError("filter number must be finite")
        if not node.left.path.segments:
            raise ArtifactReadValidationError("filter operand must name a relative member path")
        check_path(node.left.path, relative=True)

    def check_path(query, *, relative=False):
        if type(query) is not JSONPath or len(query.segments) > 16:
            raise ArtifactReadValidationError("unsupported path or more than 16 segments")
        for segment in query.segments:
            if type(segment) is not JSONPathChildSegment or len(segment.selectors) != 1:
                raise ArtifactReadValidationError(
                    "only single-selector child segments are supported"
                )
            selector = segment.selectors[0]
            if type(selector) is NameSelector:
                continue
            if type(selector) is IndexSelector and selector.index >= 0:
                continue
            if not relative and type(selector) is WildcardSelector:
                segment.selectors = (_ArrayWildcard(env=env, token=selector.token),)
            elif not relative and type(selector) is Filter:
                check_condition(selector.expression.expression)
                segment.selectors = (
                    _ArrayFilter(env=env, token=selector.token, expression=selector.expression),
                )
            else:
                raise ArtifactReadValidationError(
                    "selector is outside the supported JSONPath subset"
                )

    check_path(path)
    return path


def _record_path(parts) -> str:
    if not parts or any(isinstance(part, str) and (not part or "." in part) for part in parts):
        raise ArtifactReadValidationError("selected location is unsupported by artifact.read paths")
    return ".".join(str(part) for part in parts)


def _evaluate(
    document: Any, args: ArtifactQueryInput, max_bytes: int, max_work: int
) -> ArtifactQueryResult:
    try:
        path = _compile(args.expression, max_work)
        matches = []
        sample = None
        more = False
        for index, match in enumerate(path.finditer(document)):
            if not isinstance(match.obj, dict):
                raise ArtifactReadValidationError("query must select object records")
            location = _record_path(match.parts)
            if index < args.offset:
                continue
            if len(matches) == args.limit:
                more = True
                break
            if not matches:
                sample = match.obj
            matches.append(
                ArtifactQueryMatch(
                    path=location,
                    value={key: match.obj[key] for key in args.fields if key in match.obj},
                    missing_fields=[key for key in args.fields if key not in match.obj],
                )
            )
    except (JSONPathError, RecursionError, OverflowError) as exc:
        raise ArtifactReadValidationError("invalid or unsupported JSONPath expression") from exc

    while True:
        returned = len(matches)
        result = ArtifactQueryResult(
            **args.model_dump(),
            matches=matches,
            returned=returned,
            next_offset=args.offset + returned if more else None,
            truncated=more,
        )
        if serialized_size(result.model_dump(mode="json")) <= max_bytes:
            if more and result.next_offset > 10_000:
                raise ArtifactReadValidationError(
                    "continuation exceeds offset range; narrow the query"
                )
            absent = [
                key for key in args.fields
                if matches and all(key not in match.value for match in matches)
            ]
            if absent:
                raise QueryFieldsUnavailable(absent, matches[0].path, sample)
            return result
        if len(matches) <= 1:
            raise ArtifactReadValidationError(
                "query result exceeds observation byte limit; "
                "request fewer fields or a narrower query"
            )
        matches.pop()
        more = True


class ArtifactQuerier:
    def __init__(
        self,
        store: SessionArtifactStore,
        *,
        observation_max_bytes: int = DEFAULT_ARTIFACT_LIMITS.observation_max_bytes,
        max_work: int = DEFAULT_ARTIFACT_LIMITS.query_max_work,
    ):
        if type(max_work) is not int or max_work <= 0:
            raise ValueError("max_work must be a positive integer")
        self._store = store
        self._max_bytes = observation_max_bytes
        self._max_work = max_work

    async def query(self, args: ArtifactQueryInput) -> ArtifactQueryResult:
        document = await self._store.get(args.ref)
        # Keep the event loop cancellable. A cancelled await does not forcibly
        # stop its worker; AST/work limits bound query traversal and comparisons.
        return await asyncio.to_thread(_evaluate, document, args, self._max_bytes, self._max_work)
