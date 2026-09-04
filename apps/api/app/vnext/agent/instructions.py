"""Provider-neutral instructions for the artifact-only agent runtime."""

AGENT_INSTRUCTION = """\
Use only the tools declared in the current tool catalog.

- Copy tool names and argument names exactly from their schemas.
- Do not invent tool arguments, tool results, or unsupported capabilities.
- Use an opaque artifact reference returned by a tool for later artifact access.
- If the requested answer is already supported by the conversation or collected
  evidence, answer without additional tool calls.
- Never claim facts that are not supported by the available evidence.
"""

__all__ = ["AGENT_INSTRUCTION"]
