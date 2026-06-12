import httpx


class StratzClient:
    def __init__(self, graphql_url: str, token: str | None = None) -> None:
        self.graphql_url = graphql_url
        self.token = token

    async def query(
        self,
        query: str,
        variables: dict[str, object] | None = None,
    ) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        payload = {"query": query, "variables": variables or {}}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.graphql_url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
