# Task Plan Generalization

TaskPlan is a coverage map, not an execution script.

A good task item should satisfy four properties:

1. Independent completion — it can be completed without requiring completion of
   every other item.
2. Result alignment — it corresponds to a unit the user expects in the answer.
3. Bounded scope — it is small enough to reach a clear semantic completion
   boundary.
4. Checkpointability — its durable result can be preserved in one checkpoint.

Task partitioning must not be learned from a single temporal benchmark.

Examples:

- one team across several years may partition by year;
- many teams may partition by team;
- many players may partition by player;
- several competitions may partition by competition;
- hybrid requests may admit more than one valid axis.

There is intentionally no single correct key set or tool-call sequence.

## Anti-pattern: retrieval-stage plans

Bad:

- discover leagues
- fetch matches
- inspect artifacts
- compare results
- write answer

These are execution stages, not independently completable user-result units.

## Live evaluation

Use `apps/api/scripts/vnext_agent_console.py` to run each case in
`apps/api/tests/vnext/evals/task_plan_generalization_cases.json`.

Review:

- first `task.plan` call;
- selected partition axis;
- whether every item is bounded and independently completable;
- whether CURRENT receives execution priority;
- whether later-item evidence is only opportunistic while CURRENT is incomplete;
- whether checkpoints correspond to completed result units.

Do not fail a run only because the model selected a different acceptable axis.
