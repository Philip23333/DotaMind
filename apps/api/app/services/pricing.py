from app.api.v1.schemas import ServiceCatalogResponse, ServiceDescriptor


def service_catalog() -> ServiceCatalogResponse:
    return ServiceCatalogResponse(
        commerce_status="CAP integration planned; pricing is exposed for the MVP service contract.",
        notes=[
            "Basic meta report is priced at 0.1 USDC.",
            "Team intelligence report is priced at 0.3 USDC.",
            "Deep patch impact report is priced at 0.5 USDC.",
            "Claim verification can be bundled into report calls or exposed separately.",
        ],
        services=[
            ServiceDescriptor(
                name="get_meta_report",
                endpoint="/api/v1/meta-report",
                price_usdc=0.1,
                description="Returns ranked heroes for a game, patch, and role.",
                input_schema={"game": "dota2", "patch": "latest | patch id", "role": "offlane"},
            ),
            ServiceDescriptor(
                name="get_team_report",
                endpoint="/api/v1/team-report",
                price_usdc=0.3,
                description="Returns recent professional team intelligence.",
                input_schema={
                    "game": "dota2",
                    "team_name": "Team Spirit",
                    "time_range": "last_30_days",
                },
            ),
            ServiceDescriptor(
                name="get_patch_impact",
                endpoint="/api/v1/patch-impact",
                price_usdc=0.5,
                description="Returns winners, losers, item impacts, and lineup trends for a patch.",
                input_schema={"game": "dota2", "patch": "latest", "role": "optional role filter"},
            ),
            ServiceDescriptor(
                name="verify_meta_claim",
                endpoint="/api/v1/verify-claim",
                price_usdc=0.05,
                description="Checks whether a game meta claim has evidence support.",
                input_schema={"game": "dota2", "claim": "plain text claim"},
            ),
        ],
    )
