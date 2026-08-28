import { createUuidV4 } from "./uuid";
import { getApiUrl } from "./api-url";
import type { CatalogVisualEntity } from "./dota-visuals";

export type VNextChatEvent =
  | { type: "delta"; text: string }
  | {
      type: "completed";
      content: string;
      turn_index: number;
      catalog_visual_entities?: CatalogVisualEntity[];
    }
  | { type: "error"; error_code: string; reason: string };

function browserHeaders(browserId: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    "X-DotaMind-Browser-Id": browserId,
  };
}

async function responseError(response: Response): Promise<Error> {
  try {
    const body = (await response.json()) as { reason?: string };
    return new Error(body.reason?.trim() || `DotaMind API 请求失败（HTTP ${response.status}）。`);
  } catch {
    return new Error(`DotaMind API 请求失败（HTTP ${response.status}）。`);
  }
}

function parseEvent(line: string): VNextChatEvent {
  const value: unknown = JSON.parse(line);
  if (!value || typeof value !== "object" || !("type" in value)) {
    throw new Error("DotaMind 流式响应格式无效。");
  }
  const event = value as Record<string, unknown>;
  if (event.type === "delta" && typeof event.text === "string") {
    return { type: "delta", text: event.text };
  }
  if (
    event.type === "completed" &&
    typeof event.content === "string" &&
    typeof event.turn_index === "number"
  ) {
    const entities = event.catalog_visual_entities;
    if (entities !== undefined && !isCatalogVisualEntityList(entities)) {
      throw new Error("DotaMind 流式响应包含无效实体展示数据。");
    }
    return {
      type: "completed",
      content: event.content,
      turn_index: event.turn_index,
      ...(entities === undefined ? {} : { catalog_visual_entities: entities }),
    };
  }
  if (
    event.type === "error" &&
    typeof event.error_code === "string" &&
    typeof event.reason === "string"
  ) {
    return { type: "error", error_code: event.error_code, reason: event.reason };
  }
  throw new Error("DotaMind 流式响应包含未知事件。");
}

function isCatalogVisualEntityList(value: unknown): value is CatalogVisualEntity[] {
  return Array.isArray(value) && value.every(isCatalogVisualEntity);
}

function isCatalogVisualEntity(value: unknown): value is CatalogVisualEntity {
  if (!value || typeof value !== "object") return false;
  const entity = value as Record<string, unknown>;
  const kind = entity.kind;
  const imagePath = entity.imagePath;
  return (
    (kind === "hero" || kind === "item" || kind === "ability" || kind === "team") &&
    typeof imagePath === "string" &&
    imagePath.startsWith("/api/v1/assets/") &&
    /\.(?:png|jpe?g|webp)$/i.test(imagePath) &&
    typeof entity.label === "string" &&
    entity.label.trim().length > 0 &&
    Array.isArray(entity.names) &&
    entity.names.length > 0 &&
    entity.names.every((name) => typeof name === "string" && name.trim().length > 0)
  );
}

export async function* streamChatMessage({
  browserId,
  sessionId,
  query,
  requestId = createUuidV4(),
  signal,
}: {
  browserId: string;
  sessionId: string;
  query: string;
  requestId?: string;
  signal: AbortSignal;
}): AsyncGenerator<VNextChatEvent, void> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: browserHeaders(browserId),
    body: JSON.stringify({ request_id: requestId, query }),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new Error("DotaMind 未返回流式响应。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      let newlineIndex = pending.indexOf("\n");
      while (newlineIndex !== -1) {
        const line = pending.slice(0, newlineIndex).trim();
        pending = pending.slice(newlineIndex + 1);
        if (line) yield parseEvent(line);
        newlineIndex = pending.indexOf("\n");
      }
      if (done) break;
    }
    const trailing = pending.trim();
    if (trailing) yield parseEvent(trailing);
  } finally {
    reader.releaseLock();
  }
}
