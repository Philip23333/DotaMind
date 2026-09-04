# Evals

## Goal

Evaluation checks externally visible capability behavior, bounded Artifact
observation, generic runtime boundaries, and stable failure semantics. A passing
tool execution is not enough: tests must assert the useful result and the
provenance-bearing stored document.

## Deterministic test style

Tests use small inline payloads and local fakes. They do not depend on provider
accounts, live schedules, or credentials. Each test owns only the source fields
needed to express its rule.

The clean-slate baseline requires:

| Concern | Required assertion |
| --- | --- |
| Registry | The default registry is non-empty and every registered name starts with `artifact.` |
| Prompt | The Controller renders every registered Artifact tool and contains no removed domain rules |
| Query context | `ExecutionPlan.context` accepts only `{}` until a cross-tool contract is introduced |
| Artifact boundary | `artifact.read` and `artifact.grep` require one exact reference and remain schema-neutral |
| Runtime | Unknown tools, invalid arguments, handler failures, budgets, tracing, and persistence use stable generic behavior |

Focused tests live under `apps/api/tests/`. Run the baseline and generic runtime
tests before the full suite.

## Agent evaluations

There is no domain-agent acceptance while the clean-slate registry exposes only
Artifact tools. Domain acceptance resumes when a new closed capability is
registered with its own schema, provider boundary, deterministic tests, and
fresh live smoke coverage where needed.

Agent-level checks must verify that the model follows the rendered catalog,
uses only declared arguments and output references, stops when evidence is
sufficient, and does not claim facts unsupported by collected observations.

## Live smoke tests

Live smoke tests are separate from deterministic acceptance. They may validate a
current endpoint or real source payload only when a current integration requires
it. Provider outages, expired credentials, and changing schedules must not turn
into deterministic unit-test failures.

Never commit credentials, authorization headers, request tokens, or material
user data.
