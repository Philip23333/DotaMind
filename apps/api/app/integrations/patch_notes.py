import httpx


class PatchNotesClient:
    def __init__(self, base_url: str = "https://www.dota2.com/patches") -> None:
        self.base_url = base_url.rstrip("/")

    async def fetch_patch_page(self, patch: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{self.base_url}/{patch}")
            response.raise_for_status()
            return response.text
