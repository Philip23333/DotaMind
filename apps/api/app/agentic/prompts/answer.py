"""Provider-neutral rendering helpers for evidence-grounded answers."""

from __future__ import annotations

import json

from app.agentic.evidence import EvidenceGraph
from app.agentic.models import ExecutionPlan

ANSWER_CORE_RULES = """
Write a concise answer grounded only in the supplied evidence.
- Do not invent facts, identities, calculations, or citations.
- Distinguish explicit source facts from uncertainty and interpretation.
- If required evidence is missing, say so instead of filling the gap from model
  knowledge.
- Answer the user's requested scope and no broader claim.
""".strip()


def render_natural_language_system_prompt(graph: EvidenceGraph) -> str:
    """Render the neutral answer rules for the current evidence graph."""

    required = json.dumps(graph.required_evidence, ensure_ascii=False)
    return f"{ANSWER_CORE_RULES}\n\nRequired evidence kinds: {required}"


def _answer_evidence_view(graph: EvidenceGraph) -> dict[str, object]:
    required_kinds = set(graph.required_evidence)
    evidence = [item for item in graph.evidence if item.kind in required_kinds]
    return {
        "required_evidence": graph.required_evidence,
        "evidence": [item.model_dump(mode="json") for item in evidence],
        "missing": graph.missing,
        "data_quality": graph.data_quality.model_dump(mode="json"),
    }


def render_natural_language_answer_messages(
    plan: ExecutionPlan,
    graph: EvidenceGraph,
    *,
    current_query: str | None = None,
) -> list[dict[str, str]]:
    request_context = {
        "current_query": current_query or plan.goal,
        "reconstructed_goal": plan.goal,
    }
    answer_evidence = _answer_evidence_view(graph)
    answer_graph = graph.model_copy(
        update={
            "tool_results": [],
            "evidence": [
                item
                for item in graph.evidence
                if item.kind in set(graph.required_evidence)
            ],
        }
    )
    return [
        {"role": "system", "content": render_natural_language_system_prompt(answer_graph)},
        {
            "role": "user",
            "content": (
                "request_context="
                f"{json.dumps(request_context, ensure_ascii=False)}\n"
                f"evidence_view={json.dumps(answer_evidence, ensure_ascii=False)}"
            ),
        },
    ]
