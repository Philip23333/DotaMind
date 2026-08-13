"""Stable versions and audit metadata for Controller prompt renderers."""

from __future__ import annotations

import hashlib

RECOVERY_RULES_VERSION = "v1"

_COMPONENT_VERSIONS = {
    "controller.base": "v4",
    "controller.conversation_rules": "v3",
    "controller.catalog_renderer": "v1",
    "controller.contract_renderer": "v1",
    "controller.sample_policy_renderer": "v1",
    "controller.conversation_messages_renderer": "v1",
    "controller.validation_retry": "v2",
    "controller.recovery_rules": RECOVERY_RULES_VERSION,
}


def build_prompt_versions(system_prompt: str) -> dict[str, str]:
    """Return configured Controller component versions and its prepared prompt hash."""

    versions = dict(_COMPONENT_VERSIONS)
    versions["controller.system.sha256"] = hashlib.sha256(
        system_prompt.encode("utf-8")
    ).hexdigest()
    return versions
