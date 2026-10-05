# Model Output Budgets and Failure Recovery

> **Status: dynamic output budgets and Adapter-side tool-call batch classification are implemented and offline-tested.**
> Runtime history encoding, paired non-execution feedback, generation correction,
> and answer-truncation recovery remain pending; live Provider compatibility has
> not been verified.

This document is the single authority for dynamic model output budgets,
model-response failure representation, and bounded generation correction.
Implementation must preserve the existing production rule that execution has no
cumulative step-count ceiling: consecutive response corrections, the existing
execution deadline, and user cancellation bound this recovery path. Step numbers
remain trace metadata.

## 1. Goal and scope

The confirmed target establishes:

- a request output cap derived from model limits and optional application
  configuration, then clipped to the capacity remaining for the current input;
- strict tool-argument parsing and all-or-nothing rejection for response-level
  failures;
- paired, non-executable failure results that preserve the original call text and
  identity in conversation history;
- at most two corrective model generations after a consecutive response-level
  failure, followed by execution finalization and the existing Answer Stage;
- replacement of truncated answer attempts, followed by a deterministic fallback
  when the degraded answer is also truncated.

Dynamic budgets are implemented. The Adapter also now validates every tool call
identity and argument carrier before parsing arguments, classifies every argument
as a JSON object or a structured failure, and rejects tool-call responses ending
with `finish_reason=length`. It preserves the rejected raw batch in a typed
provider-neutral exception while attaching only existing bounded diagnostics.
Runtime still follows its existing terminal model-error path for this exception:
it does not yet create paired non-execution history results or retry generation.
The rules below define that later Runtime behavior. This work does not define
content controls, prompt policy, or a new user-visible content limit. It also does
not add a total step limit, a new retry for provider transport failures, or a
second overflow recovery allowance.

## 2. Configuration responsibilities

| Value | Responsibility |
| --- | --- |
| Model context window | Maximum estimated input plus output capacity for the selected model. It is the model's declared or explicitly configured value; Runtime does not guess it. |
| Model maximum output | Upper bound the selected model/provider supports for one response. |
| Optional application output cap | An operator ceiling that may lower the model maximum; it does not claim a model capability. |
| Context safety margin | Capacity held back for estimation error and request framing. It is applied when clipping a request and in the hard-capacity check. |
| Compaction reserve | Existing production compaction watermark and source for the existing summary budgets. It does not also act as the ordinary response output cap. |

An unset context window keeps automatic capacity governance disabled, as it is
today; it does not cause Runtime to infer a window. Summary calls retain their
separate history and turn-prefix budgets defined in
[context_governance_evidence_lifecycle.md](context_governance_evidence_lifecycle.md).

## 3. Request output budgets

Use these names consistently:

- **Expected output cap**: the response ceiling before looking at current input.
  It is the model maximum, lowered by the optional application cap when one is
  configured.
- **Actual output cap**: the expected cap clipped to the remaining capacity for
  this specific request.

Let M be the known model maximum output and A the optional application cap:

    expected_output_cap = min(M, A)     when A is configured
    expected_output_cap = M             otherwise

If the model maximum is unavailable but A is configured, A supplies the finite
expected cap. If neither value is known, reject the request as a model-capability
or configuration error before dispatch; do not invent a numeric fallback.

For a known context window W, estimated effective input I, and safety margin S:

    remaining_output = max(0, W - I - S)
    actual_output_cap = min(expected_output_cap, remaining_output)

The request capacity check uses the actual cap:

    I + actual_output_cap + S <= W

If no output space remains, do not send a request with a zero output cap. Use the
existing capacity and eligible compaction path, recalculate after input changes,
and take the existing safe capacity exit if no valid request can fit.

When W is not configured, the actual cap equals the expected cap and the
existing automatic capacity governance remains disabled. Do not invent a
universal model window or a fallback output number.

Execution calls, the primary answer, and the degraded answer use this same
calculation with their own effective input. A compaction or other legitimate
input change requires recalculating the actual cap before the next model call.
Summary calls remain independent and use their existing reserve-derived budgets
and optional summary-model cap; they do not use the ordinary business-call cap.

The test-only early-compaction percentage is based on the expected cap before
input-dependent clipping. This avoids a circular threshold:

    test_input_budget = max(0, W - expected_output_cap - S)
    test_trigger = ceil(test_input_budget * P / 100)

The existing production watermark remains I > W - R, where R is the
compaction reserve. If the test percentage is set, the effective early threshold
remains the earlier of the production and test thresholds. The actual request
capacity check still uses actual_output_cap; CRITICAL hard-capacity handling
retains priority.

Example, with values in thousands of tokens:

    W = 100, M = 40, A = 30, S = 2, R = 20, P = 30%
    expected_output_cap = min(40, 30) = 30
    test_input_budget = 100 - 30 - 2 = 68
    test_trigger = ceil(68 * 30%) = 20.4
    production trigger = I > 100 - 20, or I >= 80.001

With the test percentage unset and I = 78, the actual cap is
min(30, 100 - 78 - 2) = 20, so the complete request fits exactly. After
compaction reduces I to 65, the cap is recalculated to 30. The early test
threshold uses 30 before clipping; the request check uses the clipped 20.
There is no feedback loop between the two calculations.

`DOTAMIND_MODEL_MAX_OUTPUT_TOKENS` and
`DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS` configure the ordinary output caps. At
least one must be set for environment-loaded production settings. If both are
missing, configuration fails; direct Runtime use also fails before an ordinary
model request is dispatched. `DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS` is no
longer read and is not mapped to either cap. The existing compaction reserve
continues to set the production watermark and derive summary budgets.

## 4. Response classification

The adapter classifies a complete model response before Runtime grants any tool
execution permission:

1. **Normal complete response**: IDs and outer protocol are valid. Each tool
   argument string parses as a JSON object. Existing per-tool schema and business
   validation continues in ToolRegistry.
2. **Invalid tool-argument JSON**: at least one call's argument string is
   malformed or parses to a non-object JSON value. This is a response-level
   failure, not a ToolRegistry schema error.
3. **Tool response ended with finish_reason=length**: the response is treated
   as truncated even if every argument string received so far happens to parse.
4. **Missing or duplicate call identity, or damaged outer protocol**: preserve
   the existing protocol-error exit. Do not try to repair or execute the batch.
5. **Primary answer ended with finish_reason=length**: fail that answer attempt
   and enter the existing degraded-answer path.
6. **Degraded answer ended with finish_reason=length**: replace it with the
   deterministic fallback.
7. **Explicit provider context-window overflow**: retain the existing one-time
   compaction recovery for the user request; do not replay completed tools.
8. **Other transport, authentication, rate-limit, or provider errors**: retain
   their existing error classification and exit behavior. They are not tool JSON
   errors and do not enter this correction loop.

| Response case | Tool execution | Next action |
| --- | --- | --- |
| Complete response; every parameter JSON value is a valid object | Continue the existing flow | Ordinary ToolRegistry validation errors use existing feedback |
| Any tool parameter JSON is invalid | Reject the whole batch | Pair error results and allow bounded correction |
| Tool calls with finish_reason=length | Reject the whole batch | Pair error results and allow bounded correction |
| Missing/duplicate ID or damaged outer protocol | Do not execute | Preserve the existing protocol-error exit |
| Primary answer with finish_reason=length | No tools | Fail this answer attempt and enter degraded answer |
| Degraded answer with finish_reason=length | No tools | Replace it with deterministic fallback |
| Explicit context-window overflow | Do not replay completed tools | Keep the existing single compaction recovery |
| Other transport/authentication/rate-limit error | Not treated as a parameter error | Keep its existing handling |

Adapter classification and typed rejected-batch preservation are implemented and
offline-tested for complete and streamed responses. Runtime recovery actions in
this matrix remain target behavior until the paired history and correction work
is implemented. Protocol identity or outer-response errors still use the
existing protocol-error exit.

## 5. Whole-batch execution gate and history

This section is the target Runtime history contract. The current Adapter rejects
the entire response before returning a ModelResponse, so handlers do not run,
but Runtime still terminates through its existing model-error path and does not
yet append the paired history described here.

The Adapter waits for the response to finish and validates the outer call
identities and every raw argument string before returning a usable ModelResponse.
Runtime treats the typed rejected-batch exception as non-executable, appends its
paired feedback, and only executes a valid ModelResponse. If any argument JSON
is invalid, or a response containing tool calls ends with
finish_reason=length, the whole batch has zero executions. A call whose JSON is
valid does not get to run merely because another call in its batch failed.

For a rejected batch with valid call identities, history retains each original
raw argument string and call identity. Every call receives one matching error
result and remains non-executable:

- the failing call's result identifies the JSON parse error or explicit
  truncation;
- other calls' results explain that they were not executed because another call
  in the batch failed;
- the batch includes the uniform statement: **“本批所有调用均未执行，请重新提交完整调用。”**

The assistant call and each paired error result form a complete message group.
Context compaction may not split the group. This failed group is ordinary
conversation history, not a checkpoint source. Its error results do not change
TaskState completion or become evidence that a tool ran.

Never replace invalid arguments with {}, concatenate two model responses,
automatically repair JSON, or reconstruct returned history from truncated trace
diagnostics. Runtime history uses the original bounded conversation messages.
Trace diagnostics are evidence about a failure, not an execution data source.

For a complete response with valid argument objects, existing tool-level schema,
business, authorization, and checkpoint-source errors keep their current
per-call behavior. They are not promoted to response-level all-batch rejection.

## 6. Bounded correction loop

A failed response-level batch may cause at most **two additional model
generations**. The first invalid/truncated response is the initial failure; the
next two are correction attempts. A normal complete model response clears the
consecutive-failure count. A new response-level failure after that normal
response may use a fresh allowance.

The original execution deadline covers the first call, corrections, and all
other execution work. Correction does not reset the deadline, user cancellation
still stops the run, and there is no production total-step limit. If the shared
deadline expires or the user cancels, the existing deadline/cancellation path
wins.

This allowance is only for the response-level tool-call errors above. It does
not retry provider transport/authentication/rate-limit errors, and it does not
replace ToolRegistry's ordinary feedback for valid JSON with invalid fields.

## 7. Correction exhaustion and answer delivery

When the two corrective generations are exhausted, Runtime ends execution and
enters the existing Answer Stage. It does not jump directly to degraded_answer.
Completed TaskState items remain as recorded; Runtime does not mark incomplete
items complete and does not infer completion when no task plan exists.

The Answer Stage uses the reliable results already available:

- with completed task items or other reliable results, provide a partial answer
  and identify what could not be completed;
- with no reliable completed result, give a clear failure explanation.

If the primary answer is truncated, treat it as a failed answer attempt and
replace it through the existing attempt mechanism before starting the degraded
answer. If that answer is also truncated, replace it with deterministic fallback.
A truncated primary or degraded text is never a canonical final and is never
saved as a successful answer. Each replacement uses the existing answer-attempt
identity rules and the original shared answer deadline.

A delivered answer may make the Runtime delivery state completed; the execution
end reason and task coverage remain separate facts. An all-batch rejection is
shown as “not executed,” not as a successful tool activity.

The detailed product state contract is
[product_run_state.md](product_run_state.md).

## 8. Relationship to compaction and other retries

Invalid JSON does not itself force compaction. Normal capacity checks continue
to run on the effective request, including the paired failure history. Existing
watermark compaction and the explicit provider-overflow recovery remain available
under their current rules. When context changes, recompute the request's actual
output cap.

Keep these three mechanisms separate:

| Mechanism | Purpose and counter | Scope |
| --- | --- | --- |
| Generation correction | At most two additional generations for consecutive invalid/truncated tool-call responses; reset after a normal model response | Execution stage; uses the original execution deadline |
| Summary retry | Existing DOTAMIND_COMPACTION_MAX_RETRIES additional tries for eligible transient errors, counted per summary segment | Each summary segment; remains separate from business calls |
| Provider overflow recovery | Existing at-most-once recovery after an explicit context-window overflow | One allowance shared by execution and primary answer for the user request; completed tools are not replayed |

Every actual model call, including each correction, summary retry, and overflow
retry, counts toward trace and evaluation call totals. Waiting or bookkeeping
does not count as a model call. None of these mechanisms resets a stage deadline.

## 9. Pi reference and DotaMind choices

The comparison is pinned to Pi commit
[1eee081e29c1323c40b98db11d0a62b919831881](https://github.com/earendil-works/pi/tree/1eee081e29c1323c40b98db11d0a62b919831881).
At that commit, the Pi AI model and request types expose separate
contextWindow, model maxTokens, and request maxTokens values. Its agent loop
validates tool arguments call by call and can return an immediate error result
for a rejected call while other prepared calls in the same batch still execute.
The loop treats stopReason=error and aborted as terminal for that loop
invocation; it does not define the DotaMind response-level correction policy.
See the pinned
[agent-loop.ts](https://github.com/earendil-works/pi/blob/1eee081e29c1323c40b98db11d0a62b919831881/packages/agent/src/agent-loop.ts)
and
[types.ts](https://github.com/earendil-works/pi/blob/1eee081e29c1323c40b98db11d0a62b919831881/packages/ai/src/types.ts).

DotaMind adopts the separation between model/context limits and a per-request
output option, but makes its own choices: clip the expected output cap to
remaining input capacity, reject a whole batch on response-level parameter JSON
failure or tool-call truncation, preserve paired non-execution results, permit
two consecutive corrections, and then finalize execution into the Answer Stage.
This is a DotaMind target contract, not a claim about Pi defaults.

## 10. Implementation and acceptance status

This document records a confirmed target design. It does not mean the behavior
is implemented or accepted. Offline acceptance is specified in
[EVALS.md](../EVALS.md). Online Provider compatibility and historical response
behavior remain later verification items and cannot substitute for offline
acceptance.
