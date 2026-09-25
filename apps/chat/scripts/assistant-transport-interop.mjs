import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const capturePath = process.env.DOTAMIND_ASSISTANT_TRANSPORT_CAPTURE;
assert.ok(capturePath, "DOTAMIND_ASSISTANT_TRANSPORT_CAPTURE is required");

const packageSpecifier =
  process.env.DOTAMIND_ASSISTANT_STREAM_MODULE_URL ?? "assistant-stream";
const { AssistantTransportDecoder, AssistantTransportDeltaTracker } =
  await import(packageSpecifier);
const capture = JSON.parse(await readFile(capturePath, "utf8"));
const response = new Response(capture.wire, {
  headers: { "content-type": "text/event-stream" },
});
const decoded = [];
const reader = response.body.pipeThrough(new AssistantTransportDecoder()).getReader();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  decoded.push(value);
}

const stateChunks = decoded.filter((chunk) => chunk.type === "update-state");
assert.ok(stateChunks.length > 0, "the official decoder should yield state updates");

const tracker = new AssistantTransportDeltaTracker(null);
for (const chunk of stateChunks) tracker.append(chunk.operations);

const operations = stateChunks.flatMap((chunk) => chunk.operations);
assert.ok(
  operations.some(
    (operation) =>
      operation.type === "append-text" &&
      JSON.stringify(operation.path) === JSON.stringify(["run", "answer", "text"]),
  ),
  "streamed answer deltas should use the official append-text operation",
);
assert.ok(
  operations.some(
    (operation) =>
      operation.type === "set" &&
      JSON.stringify(operation.path) === JSON.stringify(["run", "answer"]) &&
      operation.value?.attempt_id === "fallback" &&
      operation.value?.text === "",
  ),
  "fallback should atomically replace the prior answer attempt",
);
assert.deepEqual(tracker.state, capture.expected_state);
assert.equal(tracker.state.run.status, "completed");
assert.equal(tracker.state.run.answer.status, "ready");
assert.equal(tracker.state.run.persistence, "saved");

process.stdout.write(
  `Decoded ${decoded.length} official AssistantTransport chunks; final state matches Python capture.\n`,
);
