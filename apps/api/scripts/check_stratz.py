"""Manually verify STRATZ GraphQL connectivity and hero matchup data."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.integrations.stratz.heroes import StratzHeroes
from app.integrations.stratz.transport import (
    StratzGraphQLError,
    StratzHTTPStatusError,
    StratzTransport,
    StratzTransportError,
)


def main() -> int:
    args = parse_args()
    settings = get_settings()
    if not settings.stratz_token:
        print("missing DOTAMIND_STRATZ_TOKEN", file=sys.stderr)
        return 1

    try:
        result = asyncio.run(
            check(
                settings.stratz_graphql_url,
                settings.stratz_token,
                args.hero_id,
                args.take,
            )
        )
    except StratzHTTPStatusError as exc:
        print(
            "STRATZ HTTP request failed "
            f"status={exc.status_code} content_type={exc.content_type or 'unknown'}",
            file=sys.stderr,
        )
        return 1
    except (OSError, StratzGraphQLError, StratzTransportError) as exc:
        print(f"STRATZ check failed type={type(exc).__name__} error={exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check STRATZ hero matchup data.")
    parser.add_argument("--hero-id", type=int, default=25, help="Dota hero id. Defaults to Lina.")
    parser.add_argument("--take", type=int, default=5, help="Number of rows per side.")
    return parser.parse_args()


async def check(
    graphql_url: str,
    token: str,
    hero_id: int,
    take: int,
) -> dict:
    transport = StratzTransport(graphql_url, token)
    heroes = StratzHeroes(transport)
    try:
        return await heroes.hero_vs_hero_matchup(hero_id, take=take)
    finally:
        await transport.aclose()


if __name__ == "__main__":
    raise SystemExit(main())
