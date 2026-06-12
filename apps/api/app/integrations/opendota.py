import httpx


class OpenDotaClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def get_heroes(self) -> list[dict[str, object]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=15) as client:
            response = await client.get("/heroes")
            response.raise_for_status()
            return response.json()
