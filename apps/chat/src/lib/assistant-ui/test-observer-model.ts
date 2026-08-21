import type { DotaMindObservation } from "./run-event-converter";

export type ToolObservationGroup = {
  key: string;
  attemptIndex: number;
  callId: string;
  name: string;
  input?: DotaMindObservation;
  output?: DotaMindObservation;
};

export function serializeObservationPayload(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? "null";
}

export function groupToolObservations(
  observations: DotaMindObservation[],
): ToolObservationGroup[] {
  const groups = new Map<string, ToolObservationGroup>();
  for (const observation of observations) {
    if (observation.stage !== "tool") continue;
    const key = `${observation.attempt_index}:${observation.call_id}`;
    const group = groups.get(key) ?? {
      key,
      attemptIndex: observation.attempt_index,
      callId: observation.call_id,
      name: observation.name,
    };
    if (observation.kind === "tool_input") group.input = observation;
    if (observation.kind === "tool_output") group.output = observation;
    groups.set(key, group);
  }
  return [...groups.values()];
}
