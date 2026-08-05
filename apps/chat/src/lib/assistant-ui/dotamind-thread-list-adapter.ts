import { createAssistantStream } from "assistant-stream";
import type { RemoteThreadListAdapter } from "@assistant-ui/react";

import {
  createChatSession,
  deleteChatSession,
  getChatSession,
  listChatSessions,
  renameChatSession,
  type ChatSessionSummary,
  type ChatRunStatus,
  setChatSessionPinned,
} from "@/lib/dotamind-api";
import { getSessionUnreadCount, DOTAMIND_THREAD_METADATA_EVENT } from "./thread-unread";

export type DotaMindThreadCustom = {
  isPinned: boolean;
  updatedAt: string;
  activeRunId: string | null;
  activeRunStatus: ChatRunStatus | null;
  unread: number;
};

function customMetadata(session: ChatSessionSummary): DotaMindThreadCustom {
  return {
    isPinned: session.is_pinned,
    updatedAt: session.updated_at,
    activeRunId: session.active_run?.run_id ?? null,
    activeRunStatus: session.active_run?.status ?? null,
    unread: getSessionUnreadCount(session.session_id),
  };
}

export function toRemoteThreadMetadata(session: ChatSessionSummary) {
  return {
    status: "regular" as const,
    remoteId: session.session_id,
    title: session.title,
    lastMessageAt: new Date(session.updated_at),
    custom: customMetadata(session),
  };
}

export function createDotaMindThreadListAdapter(browserId: string): RemoteThreadListAdapter {
  const dispatchMetadataChanged = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(DOTAMIND_THREAD_METADATA_EVENT));
    }
  };

  return {
    async list() {
      const sessions = await listChatSessions(browserId);
      return { threads: sessions.map(toRemoteThreadMetadata) };
    },

    async fetch(threadId) {
      const response = await getChatSession(browserId, threadId);
      return toRemoteThreadMetadata(response.session);
    },

    async initialize() {
      const session = await createChatSession(browserId);
      dispatchMetadataChanged();
      return { remoteId: session.session_id };
    },

    async rename(remoteId, newTitle) {
      await renameChatSession(browserId, remoteId, newTitle);
      dispatchMetadataChanged();
    },

    async updateCustom(remoteId, custom) {
      if (typeof custom?.isPinned !== "boolean") {
        throw new Error("DotaMind 线程只支持更新置顶状态。");
      }
      await setChatSessionPinned(browserId, remoteId, custom.isPinned);
      dispatchMetadataChanged();
    },

    async delete(remoteId) {
      await deleteChatSession(browserId, remoteId);
      dispatchMetadataChanged();
    },

    async archive() {
      throw new Error("DotaMind 当前不支持归档聊天。");
    },

    async unarchive() {
      throw new Error("DotaMind 当前不支持取消归档聊天。");
    },

    async generateTitle(remoteId) {
      const response = await getChatSession(browserId, remoteId);
      const title = response.session.title.trim();
      return createAssistantStream((controller) => {
        if (title) controller.appendText(title);
      });
    },
  };
}
