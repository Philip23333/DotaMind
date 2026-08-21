import { describe, expect, it } from "vitest";

import type { DotaMindObservation } from "./run-event-converter";
import {
  groupToolObservations,
  serializeObservationPayload,
} from "./test-observer-model";

function observation(
  kind: DotaMindObservation["kind"],
  payload: Record<string, unknown>,
): DotaMindObservation {
  return {
    type: "observer",
    kind,
    stage: "tool",
    call_id: "tool-1",
    name: "debug.tool",
    attempt_index: 0,
    payload,
  };
}

describe("test observer model", () => {
  it("pairs structured tool input and output by attempt and call id", () => {
    const groups = groupToolObservations([
      observation("tool_input", { resolved_args: { hero_id: 25 } }),
      observation("tool_output", { result: { status: "ok" } }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.name).toBe("debug.tool");
    expect(groups[0]?.input?.payload).toEqual({ resolved_args: { hero_id: 25 } });
    expect(groups[0]?.output?.payload).toEqual({ result: { status: "ok" } });
  });

  it("serializes observation payloads as formatted JSON", () => {
    expect(serializeObservationPayload({ role: "user", content: "莉娜" })).toBe(
      '{\n  "role": "user",\n  "content": "莉娜"\n}',
    );
  });
});
