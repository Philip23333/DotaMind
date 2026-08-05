"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { MenuIcon } from "lucide-react";
import { useCallback, useState } from "react";

import { ChatSidebar } from "@/components/chat-sidebar";
import { Button } from "@/components/ui/button";
import { Thread } from "@/components/thread";
import {
  getOrCreateBrowserId,
} from "@/lib/dotamind-api";
import { DotaMindRuntimeProvider } from "@/lib/assistant-ui/runtime-provider";

export const Assistant = () => {
  const [browserId] = useState(() => getOrCreateBrowserId());

  return (
    <DotaMindRuntimeProvider browserId={browserId}>
      <DotaMindChatShell browserId={browserId} />
    </DotaMindRuntimeProvider>
  );
};

function DotaMindChatShell({ browserId }: { browserId: string }) {
  const aui = useAui();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLoading = useAuiState((state) => state.threads.isLoading);
  const isThreadLoading = useAuiState((state) => state.thread.isLoading);

  const runThreadAction = useCallback(async (action: () => Promise<void>, message: string) => {
    try {
      await action();
      await aui.threads.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : message);
    }
  }, [aui]);

  return (
    <div className="flex h-dvh bg-background">
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
        <header className="flex min-h-14 shrink-0 items-center gap-2 border-b px-3 sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="size-10 md:hidden"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="打开聊天列表"
          >
            <MenuIcon className="size-5" />
          </Button>
          <div className="min-w-0">
            <div className="text-sm font-semibold tracking-tight">DotaMind</div>
            <div className="text-xs text-muted-foreground">Dota 2 智能分析助手</div>
          </div>
          {error && <div className="ml-auto truncate text-xs text-destructive">{error}</div>}
        </header>
        <div className="relative min-h-0 flex-1">
          <Thread browserId={browserId} />
        </div>
      </div>
    </div>
  );
}
