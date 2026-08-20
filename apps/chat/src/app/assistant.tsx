"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { MenuIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ChatSidebar } from "@/components/chat-sidebar";
import { StartupOverlay } from "@/components/startup-overlay";
import { Button } from "@/components/ui/button";
import { Thread } from "@/components/thread";
import {
  getOrCreateBrowserId,
} from "@/lib/dotamind-api";
import { DotaMindRuntimeProvider } from "@/lib/assistant-ui/runtime-provider";
import {
  DOTAMIND_THREAD_METADATA_EVENT,
  markDotaMindSessionRead,
} from "@/lib/assistant-ui/thread-unread";

export const Assistant = () => {
  const [browserId] = useState(() => getOrCreateBrowserId());

  return (
    <DotaMindRuntimeProvider browserId={browserId}>
      <StartupOverlay />
      <DotaMindChatShell browserId={browserId} />
    </DotaMindRuntimeProvider>
  );
};

function DotaMindChatShell({ browserId }: { browserId: string }) {
  const aui = useAui();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeSessionId = useAuiState((state) => state.threadListItem.remoteId);
  const isLoading = useAuiState((state) => state.threads.isLoading);
  const isThreadLoading = useAuiState((state) => state.thread.isLoading);

  useEffect(() => {
    if (activeSessionId) markDotaMindSessionRead(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    const reloadThreads = () => void aui.threads.reload();
    window.addEventListener(DOTAMIND_THREAD_METADATA_EVENT, reloadThreads);
    return () => window.removeEventListener(DOTAMIND_THREAD_METADATA_EVENT, reloadThreads);
  }, [aui]);

  const runThreadAction = useCallback(async (action: () => Promise<void>, message: string) => {
    try {
      await action();
      await aui.threads.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : message);
    }
  }, [aui]);

  return (
    <div className="chat-shell flex h-dvh bg-background">
      <ChatSidebar
        disabled={isLoading || isThreadLoading}
        mobileOpen={mobileSidebarOpen}
        onClose={() => setMobileSidebarOpen(false)}
        onNew={() => {
          setError(null);
          aui.threads.switchToNewThread();
          setMobileSidebarOpen(false);
        }}
        onRename={(sessionId, title) =>
          runThreadAction(
            async () => {
              await aui.threads.item({ id: sessionId }).rename(title);
            },
            "无法重命名聊天。",
          )
        }
        onPin={(sessionId, isPinned) =>
          runThreadAction(
            async () => {
              const current = aui.threads.item({ id: sessionId }).getState().custom ?? {};
              await aui.threads.item({ id: sessionId }).updateCustom({ ...current, isPinned });
            },
            "无法更新置顶状态。",
          )
        }
        onDelete={(sessionId) =>
          runThreadAction(
            async () => {
              await aui.threads.item({ id: sessionId }).delete();
            },
            "无法删除聊天。",
          )
        }
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="relative min-h-0 flex-1">
          <Button
            variant="ghost"
            size="icon"
            className="absolute left-3 top-3 z-20 size-10 bg-card/80 shadow-sm backdrop-blur md:hidden"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="打开聊天列表"
          >
            <MenuIcon className="size-5" />
          </Button>
          {error && (
            <div className="absolute right-3 top-3 z-20 max-w-[calc(100%-1.5rem)] truncate rounded-md bg-card/90 px-3 py-2 text-xs text-destructive shadow-sm backdrop-blur sm:right-6 sm:top-6">
              {error}
            </div>
          )}
          <Thread browserId={browserId} />
        </div>
      </div>
    </div>
  );
}
