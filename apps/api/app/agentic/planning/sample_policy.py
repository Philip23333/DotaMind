"""Sample-size threshold policy (stage 1).

Single source of truth lives in policy.yaml `planning.sample_policy`. This
module has two jobs:

- render_sample_policy: inject a per-tool threshold table + the 4 sample modes
  into the Controller system prompt. The Controller decides
  the value, the tool only takes evidence.
- apply_sample_policy: backfill `default` for any tool_call arg the LLM omitted
  or nulled, and record what it injected under plan.metadata["policy_applied"]
  so /debug/plan can show the decision provenance.

Stage 2 (critic sparse-sample detection + retry loop) is tracked separately.
"""

from app.agentic.models import ExecutionPlan
from app.agentic.tools import ToolDefinition, ToolRegistry
from app.core.config import AppPolicy

# The four sample-selection modes the Controller chooses between, in priority
# order. Mirrored in the prompt text below; keep in sync.
_SAMPLE_MODES_HEADER = """Sample-size policy (per tool, choose one mode per call):
- explicit: the user named a concrete sample floor (e.g. "至少 3000 场"). Copy
  that number into the tool's sample arg verbatim.
- strict: the user wants a robust / large-sample read ("稳健", "大样本",
  "高置信"). Use the tool's `strict` value.
- relaxed: the user tolerates small / cold samples ("冷门也行", "小样本也可以",
  "边缘英雄"). Use the tool's `relaxed` value.
- default: no signal either way. Use the tool's `default` value.

Priority when more than one applies: explicit > strict > relaxed > default.
Always write the chosen number into the tool's sample arg explicitly; if you
omit it the Controller backfills `default` (recorded under policy_applied), but
explicit is preferred so the decision is observable in args."""


def _known_tools(registry: ToolRegistry) -> dict[str, ToolDefinition]:
    return {definition.name: definition for definition in registry.list()}


def render_sample_policy(policy: AppPolicy, registry: ToolRegistry) -> str:
    """Render the sample-policy section for the Controller prompt.

    Typo guard: each policy tool key must be a registered tool and `arg` must
    be a real field on that tool's input_model. A config typo raises ValueError
    here (and in unit tests) rather than silently enrolling a no-op entry.
    """
    tools = _known_tools(registry)
    entries = policy.planning.sample_policy.tools
    if not entries:
        # Nothing configured: emit the mode rules alone so the Controller still
        # knows the vocabulary, with no per-tool table.
        return _SAMPLE_MODES_HEADER

    lines = [_SAMPLE_MODES_HEADER, "", "Per-tool thresholds (arg: default / relaxed / strict):"]
    for tool_name, entry in entries.items():
        definition = tools.get(tool_name)
        if definition is None:
            raise ValueError(
                f"sample_policy references unknown tool: {tool_name!r} "
                f"(not in registry; registered: {sorted(tools)})"
            )
        if entry.arg not in definition.input_model.model_fields:
            raise ValueError(
                f"sample_policy arg {entry.arg!r} is not a field of "
                f"{tool_name}.input_model "
                f"(fields: {sorted(definition.input_model.model_fields)})"
            )
        lines.append(
            f"- {tool_name}.{entry.arg}: "
            f"default={entry.default} relaxed={entry.relaxed} strict={entry.strict}"
        )
    return "\n".join(lines)


def apply_sample_policy(plan: ExecutionPlan, policy: AppPolicy) -> ExecutionPlan:
    """Backfill default sample-size args the Controller omitted or nulled.

    Mutates and returns `plan`. For each enrolled tool, if the sample arg is
    missing or None (LLM left it out or emitted JSON null), set it to the
    policy `default` and append a record to plan.metadata["policy_applied"].

    A value the LLM set explicitly (any non-None value, including 0) is left
    untouched and NOT recorded — its source is observable in args directly.
    Naming: policy_applied only records post-process injection (default
    backfill); explicit/strict/relaxed choices are NOT separately tagged. The
    key is absent (not an empty list) when nothing was injected, so /debug/plan
    never shows a misleading `policy_applied: []`.
    """
    entries = policy.planning.sample_policy.tools
    if not entries:
        return plan

    applied: list[dict] = []
    for call in plan.tool_calls:
        entry = entries.get(call.tool)
        if entry is None:
            continue  # tool not enrolled in sample_policy
        if call.args.get(entry.arg) is not None:
            continue  # LLM set it explicitly (explicit/strict/relaxed)
        call.args[entry.arg] = entry.default
        applied.append(
            {
                "tool_call_id": call.id,
                "tool": call.tool,
                "arg": entry.arg,
                "mode": "default",
                "value": entry.default,
                "reason": "sample_policy default (planner did not set it)",
            }
        )
    if applied:
        # Preserve any pre-existing records (defensive; Controller starts clean).
        plan.metadata.setdefault("policy_applied", []).extend(applied)
    return plan
