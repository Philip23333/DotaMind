import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import ValidationError

from app.agentic.models import ExecutionPlan, ToolCall
from app.agentic.references import parse_reference
from app.agentic.tools import ArgContract, ToolDefinition, ToolRegistry

NATURAL_LANGUAGE_CONTRACT = "natural_language_answer"


@dataclass(frozen=True)
class ContractSpec:
    name: str
    route: str
    required_evidence: frozenset[str] = field(default_factory=frozenset)
    allowed_required_evidence: frozenset[str] | None = None
    allowed_evidence: frozenset[str] | None = None
    required_tools: frozenset[str] = field(default_factory=frozenset)
    prompt_example: Mapping[str, Any] | None = None

    @property
    def structured(self) -> bool:
        return self.route == "structured"

    @property
    def evidence_allowlist(self) -> frozenset[str] | None:
        return self.allowed_evidence or self.allowed_required_evidence


CONTRACT_REGISTRY = {
    "patch_impact_report": ContractSpec(
        name="patch_impact_report",
        route="structured",
        required_evidence=frozenset({"patch_records"}),
        required_tools=frozenset({"patch.get_records"}),
    ),
    "role_meta_report": ContractSpec(
        name="role_meta_report",
        route="structured",
        required_evidence=frozenset({"hero_stats"}),
        allowed_evidence=frozenset({"hero_stats", "role_fit", "sample_size"}),
    ),
    "team_recent_report": ContractSpec(
        name="team_recent_report",
        route="structured",
        required_evidence=frozenset({"team_identity", "recent_matches"}),
        allowed_evidence=frozenset(
            {
                "team_identity",
                "recent_matches",
                "current_players",
                "team_hero_usage",
                "match_detail_sample",
                "sample_size",
            }
        ),
        prompt_example={
            "intent": "team_recent_performance",
            "goal": "Summarize a team's recent OpenDota evidence.",
            "output_contract": "team_recent_report",
            "tool_calls": [
                {
                    "id": "resolve_team",
                    "tool": "opendota.resolve_team",
                    "args": {"query": "<team query>"},
                },
                {
                    "id": "get_matches",
                    "tool": "opendota.team_recent_matches",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "days": 30,
                    },
                },
                {
                    "id": "get_players",
                    "tool": "opendota.team_players",
                    "args": {
                        "team_id": "$resolve_team.data.team.team_id",
                        "current_only": True,
                    },
                },
                {
                    "id": "get_heroes",
                    "tool": "opendota.team_heroes",
                    "args": {"matches": "$get_matches.data.matches"},
                },
            ],
            "required_evidence": [
                "team_identity",
                "recent_matches",
                "current_players",
                "team_hero_usage",
            ],
            "constraints": {"max_tool_calls": 6, "allow_mock": False},
        },
    ),
    NATURAL_LANGUAGE_CONTRACT: ContractSpec(
        name=NATURAL_LANGUAGE_CONTRACT,
        route="natural_language",
    ),
}

STRUCTURED_OUTPUT_CONTRACTS = {
    name for name, spec in CONTRACT_REGISTRY.items() if spec.structured
}
ALLOWED_OUTPUT_CONTRACTS = set(CONTRACT_REGISTRY)


def get_contract(name: str) -> ContractSpec | None:
    return CONTRACT_REGISTRY.get(name)


def known_evidence_kinds(registry: ToolRegistry) -> set[str]:
    return {
        evidence_kind
        for definition in registry.list()
        for evidence_kind in definition.evidence_kinds
    }


def render_planner_contracts(registry: ToolRegistry) -> str:
    available_evidence = known_evidence_kinds(registry)
    sections = []
    for spec in CONTRACT_REGISTRY.values():
        allowed = spec.evidence_allowlist
        visible_allowed = sorted(allowed & available_evidence) if allowed else None
        allowed_required = sorted(
            (spec.evidence_allowlist or available_evidence) & available_evidence
        )
        sections.append(
            "\n".join(
                [
                    f"- {spec.name}",
                    f"  route: {spec.route}",
                    "  required_evidence: "
                    + json.dumps(sorted(spec.required_evidence)),
                    "  allowed_evidence: " + json.dumps(visible_allowed),
                    "  required_evidence_names_must_be_exact: "
                    + json.dumps(allowed_required),
                    "  rule: Copy required_evidence entries exactly from "
                    "required_evidence/allowed_evidence/tool evidence_produced. "
                    "Do not invent synonyms.",
                    "  example: "
                    + (
                        json.dumps(spec.prompt_example, ensure_ascii=False)
                        if spec.prompt_example
                        else "null"
                    ),
                ]
            )
        )
    return "\n".join(sections)


def render_planner_tools(registry: ToolRegistry) -> str:
    sections = []
    for definition in registry.list():
        fields = definition.input_model.model_fields
        arg_names = list(fields)
        lines = [
            f"- {definition.name}",
            f"  description: {definition.description}",
            "  evidence_produced: " + json.dumps(list(definition.evidence_kinds)),
            "  produced_evidence_names_must_be_exact: "
            + json.dumps(list(definition.evidence_kinds)),
            "  allowed_arg_keys: " + json.dumps(arg_names),
            "  rule: Use only allowed_arg_keys for args. Do not invent aliases "
            "or synonyms.",
            "  args:",
        ]
        if not fields:
            lines.append("    []")
        for name, field_info in fields.items():
            contract = definition.arg_contracts.get(name, ArgContract())
            required = _field_required(name, definition)
            type_name = _type_name(field_info.annotation)
            description = contract.description or (field_info.description or "")
            line = f"    - {name}: {type_name}, "
            line += "required" if required else "optional"
            if description:
                line += f". {description}"
            lines.append(line)
            for accepted in contract.accepts_refs:
                lines.append(
                    "      accepted_ref: "
                    f"from_tool={accepted.from_tool}; "
                    f"path={accepted.path}; type={accepted.type}; "
                    f"syntax=$<previous_call_id>.{accepted.path}"
                )
                lines.append(
                    "      accepts reference from "
                    f"{accepted.from_tool}: $<previous_call_id>.{accepted.path} "
                    f"({accepted.type})"
                )
        if definition.output_paths:
            lines.append("  declared_output_paths:")
            for output in definition.output_paths.values():
                description = f". {output.description}" if output.description else ""
                lines.append(f"    - {output.path}: {output.type}{description}")
        sections.append("\n".join(lines))
    return "\n".join(sections)


def validate_plan_against_catalog(
    plan: ExecutionPlan,
    registry: ToolRegistry,
) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_registry_contracts(registry))
    errors.extend(validate_tool_calls(plan, registry))
    errors.extend(validate_references(plan, registry))
    errors.extend(validate_tool_args(plan, registry))
    errors.extend(validate_output_contract(plan, registry))
    errors.extend(validate_evidence_producibility(plan, registry))
    return errors


def validate_registry_contracts(registry: ToolRegistry) -> list[str]:
    errors: list[str] = []
    definitions = {definition.name: definition for definition in registry.list()}

    for definition in definitions.values():
        fields = definition.input_model.model_fields
        unknown_args = sorted(set(definition.arg_contracts) - set(fields))
        if unknown_args:
            errors.append(
                f"{definition.name} arg_contracts reference unknown args: "
                + ", ".join(unknown_args)
            )

        for arg_name, arg_contract in definition.arg_contracts.items():
            field = fields.get(arg_name)
            if field is None:
                continue
            for accepted in arg_contract.accepts_refs:
                if not _contract_type_matches_annotation(
                    accepted.type,
                    field.annotation,
                ):
                    errors.append(
                        f"{definition.name}.{arg_name} accepts_ref type "
                        f"{accepted.type} is incompatible with input field "
                        f"{_type_name(field.annotation)}"
                    )

                source_definition = definitions.get(accepted.from_tool)
                if source_definition is None:
                    errors.append(
                        f"{definition.name}.{arg_name} accepts_ref unknown tool: "
                        f"{accepted.from_tool}"
                    )
                    continue

                output_contract = _output_contract_for_path(
                    source_definition,
                    accepted.path,
                )
                if output_contract is None:
                    errors.append(
                        f"{definition.name}.{arg_name} accepts_ref path is not "
                        f"declared by {accepted.from_tool}: {accepted.path}"
                    )
                    continue
                if output_contract.type != accepted.type:
                    errors.append(
                        f"{definition.name}.{arg_name} accepts_ref type "
                        f"{accepted.type} does not match {accepted.from_tool} "
                        f"output path {accepted.path} type {output_contract.type}"
                    )
    return errors


def validate_tool_calls(plan: ExecutionPlan, registry: ToolRegistry) -> list[str]:
    errors: list[str] = []
    registered = {definition.name for definition in registry.list()}
    seen: set[str] = set()

    for call in plan.tool_calls:
        if call.id in seen:
            errors.append(f"duplicate tool call id: {call.id}")
        seen.add(call.id)
        if call.tool not in registered:
            errors.append(f"unknown tool: {call.tool}")

    if plan.constraints.allow_mock:
        errors.append("constraints.allow_mock must be false")
    if len(plan.tool_calls) > plan.constraints.max_tool_calls:
        errors.append(
            "plan exceeds max_tool_calls "
            f"({len(plan.tool_calls)} > {plan.constraints.max_tool_calls})"
        )
    return errors


def validate_references(plan: ExecutionPlan, registry: ToolRegistry) -> list[str]:
    errors: list[str] = []
    previous: dict[str, ToolCall] = {}
    registered = {definition.name for definition in registry.list()}

    for call in plan.tool_calls:
        if call.tool not in registered:
            previous[call.id] = call
            continue

        target_definition = registry.get(call.tool)
        for arg_name, value in call.args.items():
            if arg_name not in target_definition.input_model.model_fields:
                continue
            arg_contract = target_definition.arg_contracts.get(arg_name, ArgContract())
            for reference in _find_references(value):
                parsed = parse_reference(reference)
                if parsed is None:
                    errors.append(f"{call.id}.{arg_name} invalid reference: {reference}")
                    continue

                source_call = previous.get(parsed.call_id)
                if source_call is None:
                    errors.append(
                        f"{call.id}.{arg_name} reference target must be a previous "
                        f"tool call: {reference}"
                    )
                    continue
                if source_call.tool not in registered:
                    continue

                source_definition = registry.get(source_call.tool)
                output_contract = _output_contract_for_path(
                    source_definition,
                    parsed.path,
                )
                if output_contract is None:
                    errors.append(
                        f"{call.id}.{arg_name} reference path is not declared by "
                        f"{source_call.tool}: {parsed.path}"
                    )
                    continue

                if not any(
                    accepted.from_tool == source_definition.name
                    and accepted.path == output_contract.path
                    and accepted.type == output_contract.type
                    for accepted in arg_contract.accepts_refs
                ):
                    errors.append(
                        f"{call.id}.{arg_name} does not accept reference "
                        f"from {source_definition.name}.{output_contract.path}"
                    )
        previous[call.id] = call
    return errors


def validate_tool_args(plan: ExecutionPlan, registry: ToolRegistry) -> list[str]:
    errors: list[str] = []
    registered = {definition.name for definition in registry.list()}
    for call in plan.tool_calls:
        if call.tool not in registered:
            continue
        errors.extend(_validate_tool_args(call.tool, call.args, registry))
    return errors


def validate_output_contract(plan: ExecutionPlan, registry: ToolRegistry) -> list[str]:
    return validate_contract_plan_with_evidence(plan, known_evidence_kinds(registry))


def validate_evidence_producibility(
    plan: ExecutionPlan,
    registry: ToolRegistry,
) -> list[str]:
    registered = {definition.name for definition in registry.list()}
    produced = {
        evidence_kind
        for call in plan.tool_calls
        if call.tool in registered
        for evidence_kind in registry.get(call.tool).evidence_kinds
    }
    missing = sorted(set(plan.required_evidence) - produced)
    if missing:
        return [
            "required_evidence is not producible by selected tools: "
            + ", ".join(missing)
        ]
    return []


def validate_contract_plan_with_evidence(
    plan: ExecutionPlan,
    evidence_kinds: set[str],
) -> list[str]:
    spec = get_contract(plan.output_contract)
    if spec is None:
        return [f"unknown output_contract: {plan.output_contract}"]

    errors: list[str] = []
    required = set(plan.required_evidence)
    unknown_evidence = sorted(required - evidence_kinds)
    if unknown_evidence:
        errors.append("unknown required_evidence: " + ", ".join(unknown_evidence))

    missing = sorted(spec.required_evidence - required)
    if missing:
        errors.append(
            f"{plan.output_contract} plan missing required evidence: "
            + ", ".join(missing)
        )

    allowlist = spec.evidence_allowlist
    if allowlist is not None:
        invalid = sorted(required - allowlist)
        if invalid:
            errors.append(
                f"{plan.output_contract} required_evidence must use only "
                + ", ".join(sorted(allowlist))
                + "; got "
                + ", ".join(invalid)
            )

    tools = {call.tool for call in plan.tool_calls}
    missing_tools = sorted(spec.required_tools - tools)
    if missing_tools:
        errors.append(
            f"{plan.output_contract} plan must use " + ", ".join(missing_tools)
        )

    return errors


def _validate_tool_args(
    tool_name: str,
    args: dict[str, Any],
    registry: ToolRegistry,
) -> list[str]:
    definition = registry.get(tool_name)
    fields = definition.input_model.model_fields
    errors = []
    unknown = sorted(set(args) - set(fields))
    if unknown:
        errors.append(f"{tool_name} unknown args: " + ", ".join(unknown))
        return errors

    normalized = {
        name: _replace_references(value, fields[name].annotation)
        for name, value in args.items()
        if name in fields
    }
    try:
        definition.input_model.model_validate(normalized)
    except ValidationError as exc:
        errors.append(f"{tool_name} invalid args: {exc.errors()}")
    return errors


def _find_references(value: Any) -> list[str]:
    if isinstance(value, str) and value.startswith("$"):
        return [value]
    if isinstance(value, dict):
        return [
            reference
            for item in value.values()
            for reference in _find_references(item)
        ]
    if isinstance(value, list):
        return [reference for item in value for reference in _find_references(item)]
    return []


def _output_contract_for_path(definition: ToolDefinition, path: str):
    for contract in definition.output_paths.values():
        if contract.path == path:
            return contract
    return None


def _replace_references(value: Any, annotation: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return _placeholder(annotation)
    if isinstance(value, dict):
        return {key: _replace_references(item, Any) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_references(item, Any) for item in value]
    return value


def _field_required(name: str, definition: ToolDefinition) -> bool:
    return definition.input_model.model_fields[name].is_required()


def _type_name(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin in {Union, UnionType}:
        return " | ".join(_type_name(item) for item in get_args(annotation))
    if origin is list:
        args = get_args(annotation)
        return f"list[{_type_name(args[0])}]" if args else "list"
    if origin is dict:
        args = get_args(annotation)
        if len(args) == 2:
            return f"dict[{_type_name(args[0])}, {_type_name(args[1])}]"
        return "dict"
    if annotation is type(None):
        return "None"
    if annotation is Any:
        return "Any"
    return getattr(annotation, "__name__", str(annotation))


def _contract_type_matches_annotation(contract_type: str, annotation: Any) -> bool:
    if annotation is Any:
        return True
    origin = get_origin(annotation)
    if origin in {Union, UnionType}:
        return any(
            item is not type(None)
            and _contract_type_matches_annotation(contract_type, item)
            for item in get_args(annotation)
        )
    if contract_type == _type_name(annotation):
        return True
    if contract_type == "list[dict]" and origin is list:
        args = get_args(annotation)
        return bool(args and get_origin(args[0]) is dict)
    if contract_type == "list" and origin is list:
        return True
    if contract_type == "dict" and origin is dict:
        return True
    return False


def _placeholder(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin in {Union, UnionType}:
        non_none = [item for item in get_args(annotation) if item is not type(None)]
        return _placeholder(non_none[0]) if non_none else None
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return False
    if annotation is str:
        return "ref"
    if origin is list or annotation is list:
        return []
    if origin is dict or annotation is dict:
        return {}
    return "ref"
