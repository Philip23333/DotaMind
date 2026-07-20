"""Stable versions and audit metadata for Controller prompt renderers."""

from __future__ import annotations

import hashlib
import json

_COMPONENT_VERSIONS = {
    "controller.base": "v1",
    "controller.conversation_rules": "v1",
    "controller.catalog_renderer": "v1",
    "controller.contract_renderer": "v1",
    "controller.sample_policy_renderer": "v1",
    "controller.history_renderer": "v1",
    "controller.user_message_renderer": "v1",
    "controller.validation_retry": "v1",
}

RECOVERY_RULES_VERSION = "v1"


def build_prompt_versions(
    system_prompt: str,
    *,
    history_window: int,
    history_max_chars: int,
) -> dict[str, str]:
    """Return configured Controller component versions and its prepared prompt hash."""

    versions = dict(_COMPONENT_VERSIONS)
    versions["controller.system.sha256"] = hashlib.sha256(
        system_prompt.encode("utf-8")
    ).hexdigest()
    versions["controller.history_policy.sha256"] = hashlib.sha256(
        json.dumps(
            {
                "history_max_chars": history_max_chars,
                "history_window": history_window,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return versions
