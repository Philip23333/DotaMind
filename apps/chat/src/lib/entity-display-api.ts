import { getApiUrl } from "@/lib/api-url";

export type DisplayEntityKind = "hero" | "item" | "ability" | "team";

export type ResolvedDisplayEntity = {
  display_ref: string;
  kind: DisplayEntityKind;
  label: string;
  image_url: string | null;
};

const LOCAL_IMAGE_PATH = /^\/api\/v1\/assets\/dota\/by-hash\/[a-f0-9]{64}\.png$/;
const DISPLAY_REF =
  /^display:(?:valve:(?:hero|item|ability)|pandascore:team):[1-9][0-9]*$/;

export function isDisplayReference(value: string): boolean {
  return DISPLAY_REF.test(value);
}

export function displayKindForReference(value: string): DisplayEntityKind | null {
  const match = /^display:(?:valve:(hero|item|ability)|pandascore:(team)):[1-9][0-9]*$/.exec(value);
  const kind = match?.[1] ?? match?.[2];
  if (kind === "hero" || kind === "item" || kind === "ability" || kind === "team") {
    return kind;
  }
  return null;
}

export async function resolveDisplayRefs(
  refs: readonly string[],
  signal?: AbortSignal,
): Promise<Record<string, ResolvedDisplayEntity>> {
  const uniqueRefs = [...new Set(refs)].filter(isDisplayReference);
  const resolved: Record<string, ResolvedDisplayEntity> = {};

  for (let offset = 0; offset < uniqueRefs.length; offset += 100) {
    if (signal?.aborted) break;
    const batch = uniqueRefs.slice(offset, offset + 100);
    const response = await fetch(`${getApiUrl()}/api/v1/display/resolve`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refs: batch }),
      signal,
    });
    if (!response.ok) throw new Error("entity display resolution failed");

    const payload: unknown = await response.json();
    const entities = readEntities(payload, new Set(batch));
    Object.assign(resolved, entities);
  }

  return resolved;
}

function readEntities(
  payload: unknown,
  requested: ReadonlySet<string>,
): Record<string, ResolvedDisplayEntity> {
  if (!isRecord(payload) || !isRecord(payload.entities)) {
    throw new Error("invalid entity display response");
  }

  const result: Record<string, ResolvedDisplayEntity> = {};
  for (const ref of requested) {
    if (!Object.hasOwn(payload.entities, ref)) continue;
    const candidate: unknown = payload.entities[ref];
    if (!isRecord(candidate)) continue;
    const expectedKind = displayKindForReference(ref);
    if (
      expectedKind === null
      ||
      candidate.display_ref !== ref
      || candidate.kind !== expectedKind
      || typeof candidate.label !== "string"
      || !candidate.label.trim()
      || (candidate.image_url !== null && typeof candidate.image_url !== "string")
    ) {
      continue;
    }

    const imageUrl = candidate.image_url;
    result[ref] = {
      display_ref: ref,
      kind: expectedKind,
      label: candidate.label,
      image_url:
        typeof imageUrl === "string" && LOCAL_IMAGE_PATH.test(imageUrl)
          ? imageUrl
          : null,
    };
  }
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
