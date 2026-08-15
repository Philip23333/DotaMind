# 2026-08-15 Progress Snapshot

## 11:10 — P-15 Controller conversation-recall example debiasing

### Completed

- Replaced the Controller prompt's fixed `conversation_recall -> context_missing` JSON example with a neutral `context_missing` field shape and removed the copyable “当前会话中没有足够的历史信息” failure text.
- Preserved the `ContextMissingDecision` output shape (`kind`, `intent`, and `reason`) without adding keyword routing, fixed intent branches, deterministic recall templates, or validators.
- Updated the Controller golden prompt fixture and added assertions preventing the fixed `conversation_recall` mapping and Chinese failure text from returning to the system prompt.
- The current default Controller system prompt is 33,718 characters and 512 lines, with SHA-256 `b8b6f18f1bd2a51076af73d6c789e004fe3796523630d8fa049254ac7606d427`.

### Verification

- `tests/test_agentic_prompts.py`: 12 passed; focused Ruff checks passed.
- Ran six scenarios three times each (18 real samples) through isolated durable Chat Run sessions against a temporary port-8002 API instance loaded from the current source. Every session was deleted with HTTP 204; the temporary API was stopped and its port was closed.
- Before the change: 4/18 `direct_answer`, 14/18 `context_missing`; after the change: 14/18 `direct_answer`, 4/18 `context_missing`.
- After the change, “what was my previous question,” “what did you just answer,” and “which two heroes did I ask about” each passed 3/3. Generic “what did I just ask” passed 1/3, while both two-question phrasings passed 2/3.

### Known boundary

- Removing the misleading example materially improved meta-conversation recall but did not fully close the issue; generic user-question recall can still incorrectly return `context_missing`.
- P-15 remains partially improved. A follow-up should evaluate the smallest positive decision hint against the same real matrix without introducing deterministic Chinese-keyword branches.

## 11:36 — P-15 explicit recent-conversation rule experiment and rollback

### Experiment

- Temporarily added an explicit conversation rule stating that messages already present between the system and current user message are available conversation, and that `context_missing` is invalid and `conversation.history_lookup` unnecessary when the requested content appears there.
- Ran seven scenarios three times each (21 isolated durable Chat Runs) against a temporary port-8002 API loaded from the experimental source. The added scenario used the exact observed wording “我刚才问的什么”.

### Results

- Both generic phrasings (“我刚才问了什么” and “我刚才问的什么”) passed 0/3; explicit previous-question recall passed 2/3; “which two questions” passed 0/3.
- “List my two questions,” assistant-answer recall, and two-hero recall each passed 3/3.
- The 18 scenarios shared with the prior matrix produced only 11/18 `direct_answer`, below the 14/18 result after removing the negative example; the added exact-wording scenario was another 0/3.

### Decision and verification

- The rule provided no verified benefit and duplicated existing history rules, so it was rolled back from source, test assertions, and the golden fixture. The final code retains only the neutral `context_missing` shape change from 11:10.
- After rollback, `tests/test_agentic_prompts.py`: 12 passed. Every temporary session was deleted with HTTP 204; the temporary API was stopped and port 8002 was closed.
- Further synonymous history-availability reminders should not be added. A follow-up must reassess the responsibility boundary between `context_missing`, `conversation.history_lookup`, and model decision-making.

## 12:10 — P-15 conversation-context result destination and empty-lookup summary

### Completed

- Reduced the Controller responsibilities for supplied messages, `conversation.history_lookup`, and `context_missing` to three definitions: supplied request messages are available conversation context; lookup only adds older messages and is not Dota evidence; `context_missing` applies only after considering supplied messages and any completed lookup.
- Added `ToolDefinition.result_destination` with `evidence` and `controller_context` values. Graph routing, ControllerDecision validation, and Registry consistency checks now use that field; tool-name comparisons for `conversation.history_lookup` were removed.
- After a successful `controller_context` tool, messages merge into request-local `retrieved_messages` and a minimal `controller_context_summaries` entry is retained. An empty lookup now appears in the next Controller system input as `{"tool":"conversation.history_lookup","status":"completed","matched_turns":0}`.
- Narrowed the lookup ToolDefinition description to capability only. `result_destination` remains a runtime contract and is not added to every rendered tool prompt entry.
- Updated the Controller golden fixture, current architecture, Controller, Conversation Memory, Tool, node inventory, and Prompt-refactor review documents. The current default Controller system prompt is 33,734 characters and 514 lines, with SHA-256 `0b24cc98e928e6db22006aacfef36b95b1432f6677f87d1ec8bbfac5c8fbf6e2`.

### Verification

- `tests/test_history_lookup.py tests/test_controller_decisions.py tests/test_agentic_prompts.py -q`: 29 passed.
- `tests/test_agentic_contracts.py tests/test_agentic_registry.py -q`: 52 passed.
- Focused Ruff checks passed; `git diff --check` passed with only the existing CRLF conversion warnings.

### Known boundary

- This change covers the Prompt and context-result flow only. The durable Chat Run matrix was not rerun against a real LLM, so P-15 model-level stability still needs the same scenario-set retest.
- `conversation.history_lookup` is currently the only tool declaring the `controller_context` destination; the budget configuration remains named `history_lookup_max_per_run`.

## 12:22 — P-15 real retest after the structural fix

### Results

- Retested the prior failure scenarios through isolated durable Chat Run sessions against a temporary port-8002 API loaded from the current worktree.
- After “你有什么工具可用”: `我刚才问的什么` passed 0/3, `我刚才问了什么` passed 0/3, and `我上一个问题是什么` passed 0/3.
- After both “你有什么工具可用” and “你有什么功能”: `我刚才问过哪两个问题` passed 0/3.
- Overall: 0/12 `direct_answer` and 12/12 `context_missing`. Every recall request used one Controller call and did not execute history lookup.
- The first sample's public transcript clearly contained the complete prior user/assistant turn. In one two-question sample, the failure reason even identified the two historical topics (“available tools” and “features”) but still selected `context_missing`.

### Empty-lookup path

- Two additional requests explicitly required `conversation.history_lookup` for absent older content. Both completed the tool and entered a second Controller call.
- Both second Controller calls planned lookup again, hit `history_lookup_max_per_run=1`, and surfaced `execution_error` instead of the expected `context_missing`.
- The empty-result summary therefore closes the runtime state-loss gap, but the current model does not reliably adopt the intended terminal meaning. The repeated-lookup budget terminal mapping is a newly exposed secondary issue.

### Cleanup and conclusion

- All test sessions were deleted. The temporary port-8002 API was stopped, its listener closed, and its temporary log directory removed; the existing port-8001 service was untouched.
- P-15 remains an open P0. The next step is to revisit the decision contract and model behavior rather than assume the Prompt simplification solved the issue.
