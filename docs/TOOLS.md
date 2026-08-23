# Tools

## Design rules

Agent-visible tools are independent Dota domain capabilities. They accept
domain references or user-facing queries and return normalized domain objects.
They do not expose provider endpoints, provider identifier conversion, raw
provider payloads, or a hard-coded multi-step workflow.

Each tool description states only its purpose, input, output, and material
boundary. Domain services may call multiple providers internally when that is
necessary to make the capability reliable.

## Initial target surface

| Tool | Purpose | Input | Output | Boundary |
| --- | --- | --- | --- | --- |
| competitions.search | Find a competition or edition | Query, optional year | Competition candidates | Ambiguity remains explicit |
| competitions.list_matches | List a competition schedule | Competition reference, status or time scope | Scheduled, running, or completed matches | Schedules are volatile |
| matches.search | Find a series or game | Teams, competition, time, or query | Match candidates | Does not guess a unique match |
| matches.get_detail | Explain a resolved match or game | Match or game reference | Result, draft, scoreboard, and available game detail | Cross-source identity is disclosed |
| teams.search | Find a professional team | Query | Team candidates | Name collisions remain explicit |
| teams.list_matches | Show team schedule or recent results | Team reference, time scope | Matches | No aggregated meta analysis |
| teams.get_roster | Show known roster context | Team reference | Players and roster metadata | Source freshness is disclosed |
| players.search | Find a professional player | Query, optional team context | Player candidates | Identity ambiguity remains explicit |
| players.list_matches | Show a player's match record | Player reference, time scope | Matches and participation | Coverage depends on provider data |
| players.get_match_performance | Show one player's game performance | Player and game references | Stats, hero, and result context | Only recorded game facts |
| players.get_match_build | Show one player's build | Player and game references | Items, skill upgrades, talents, and timing where available | Missing parse data is explicit |
| catalog.get_hero | Explain a hero | Hero query or reference | Hero, abilities, and talents | Static facts only |
| catalog.get_item | Explain an item | Item query or reference | Item, recipe, and attributes | Static facts only |

The implementation may begin with fewer tools. New tools require an explicit
product need and evaluation coverage; restoring Legacy tool count is not a goal.

## Boundaries

- The model may compose domain tools naturally but no tool encodes a full
  user-scenario workflow.
- Provider selection and ID conversion happen inside domain services.
- Tools return source and freshness information with facts that can change.
- A capability that is unsupported, ambiguous, or missing upstream data returns
  that boundary explicitly instead of producing an approximate answer.
