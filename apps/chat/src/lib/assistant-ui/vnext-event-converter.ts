import type { ChatModelRunResult } from "@assistant-ui/react";

import { streamChatMessage } from "@/lib/vnext-chat-api";
import { decorateCatalogMentions } from "../dota-visuals";
import { markDotaMindSessionUnread } from "./thread-unread";

export async function* streamVNextChatMessage({
  browserId,
  sessionId,
  query,
  abortSignal,
}: {
  browserId: string;
  sessionId: string;
  query: string;
  abortSignal: AbortSignal;
}): AsyncGenerator<ChatModelRunResult, void> {
  let content = "";
  for await (const event of streamChatMessage({
    browserId,
    sessionId,
    query,
    signal: abortSignal,
  })) {
    if (abortSignal.aborted) return;
    if (event.type === "delta") {
      content += event.text;
      yield { content: [{ type: "text", text: content }] };
      continue;
    }
    if (event.type === "completed") {
      markDotaMindSessionUnread(sessionId);
      const finalText =
        decorateCatalogMentions(event.content, event.catalog_visual_entities ?? []) ?? event.content;
      yield { content: [{ type: "text", text: finalText }] };
      return;
    }
    yield { content: [{ type: "text", text: `本次请求未完成：${event.reason}` }] };
    return;
  }
  if (!abortSignal.aborted) {
    yield { content: [{ type: "text", text: "连接在收到最终结果前结束，请重试。" }] };
  }
}
