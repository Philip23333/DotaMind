from app.data.mock_data import MOCK_PATCH_IMPACT


class PatchAgent:
    """Patch-note interpreter placeholder for the MVP service contract."""

    def summarize_patch(self, patch: str) -> dict[str, object]:
        return {"patch": patch, **MOCK_PATCH_IMPACT}
