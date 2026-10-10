import { afterEach, describe, expect, it, vi } from "vitest";

import { displayKindForReference, resolveDisplayRefs } from "@/lib/entity-display-api";

function entity(ref: string, overrides: Record<string, unknown> = {}) {
  return {
    display_ref: ref,
    kind: displayKindForReference(ref),
    label: `Label ${ref.split(":").at(-1)}`,
    image_url: null,
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("entity display API", () => {
  it("deduplicates and resolves more than 100 references in sequential batches", async () => {
    const calls: Array<{ url: string; body: { refs: string[] } }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = JSON.parse(String(init?.body)) as { refs: string[] };
      calls.push({ url, body });
      return new Response(JSON.stringify({
        entities: Object.fromEntries(body.refs.map((ref) => [ref, entity(ref)])),
      }), { status: 200, headers: { "content-type": "application/json" } });
    }));

    const refs = Array.from({ length: 205 }, (_, index) => `display:valve:hero:${index + 1}`);
    const resolved = await resolveDisplayRefs([...refs, refs[0]!, "display:valve:hero:0"]);

    expect(calls.map((call) => call.body.refs.length)).toEqual([100, 100, 5]);
    expect(calls.map((call) => call.url)).toEqual(Array(3).fill(
      "http://localhost:8001/api/v1/display/resolve",
    ));
    expect(calls.every((call) => call.body.refs.length <= 100)).toBe(true);
    expect(Object.keys(resolved)).toHaveLength(205);
    expect(Object.keys(resolved)).not.toContain("display:valve:hero:0");
  });

  it("accepts only requested entities with matching identity and a local content-addressed image", async () => {
    const hero = "display:valve:hero:14";
    const item = "display:valve:item:1";
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      entities: {
        [hero]: entity(hero, { image_url: "/api/v1/assets/dota/by-hash/" + "a".repeat(64) + ".png" }),
        [item]: entity(item, { image_url: "https://cdn.example/item.png" }),
        "display:valve:hero:99": entity("display:valve:hero:99"),
        "display:valve:ability:1": entity("display:valve:ability:1"),
      },
    }), { status: 200 })));

    const resolved = await resolveDisplayRefs([hero, item]);

    expect(resolved[hero]?.image_url).toBe(`/api/v1/assets/dota/by-hash/${"a".repeat(64)}.png`);
    expect(resolved[item]?.image_url).toBeNull();
    expect(resolved).not.toHaveProperty("display:valve:hero:99");
    expect(resolved).not.toHaveProperty("display:valve:ability:1");
    expect(displayKindForReference("display:valve:hero:014")).toBeNull();
  });

  it("does not request when there are no valid references and propagates request failures", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(await resolveDisplayRefs(["ordinary text", "display:valve:hero:0"])).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValueOnce(new Response("{}", { status: 503 }));
    await expect(resolveDisplayRefs(["display:valve:hero:14"])).rejects.toThrow(
      "entity display resolution failed",
    );
  });
});
