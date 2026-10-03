"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import {
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  PanelRightCloseIcon,
  PanelRightOpenIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChatSidebar } from "@/components/chat-sidebar";
import { SessionTracePanel } from "@/components/session-trace-panel";
import { StartupOverlay } from "@/components/startup-overlay";
import { TestObserverDrawer } from "@/components/test-observer-drawer";
import { Button } from "@/components/ui/button";
import { Thread } from "@/components/thread";
import {
  getOrCreateBrowserId,
} from "@/lib/dotamind-api";
import { DotaMindRuntimeProvider } from "@/lib/assistant-ui/runtime-provider";
import {
  DOTAMIND_THREAD_METADATA_EVENT,
  useActiveSessionReadState,
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

export function DotaMindChatShell({ browserId }: { browserId: string }) {
  const aui = useAui();
  const [isDesktop, setIsDesktop] = useState(false);
  const [desktopLeftOpen, setDesktopLeftOpen] = useState(false);
  const [desktopRightOpen, setDesktopRightOpen] = useState(false);
  const [mobileDrawer, setMobileDrawer] = useState<"left" | "right" | null>(null);
  const leftToggleRef = useRef<HTMLButtonElement>(null);
  const rightToggleRef = useRef<HTMLButtonElement>(null);
  const leftDrawerRef = useRef<HTMLElement>(null);
  const rightDrawerRef = useRef<HTMLElement>(null);
  const [error, setError] = useState<string | null>(null);
  const activeSessionId = useAuiState((state) => state.threadListItem.remoteId);
  const isLoading = useAuiState((state) => state.threads.isLoading);
  const isThreadLoading = useAuiState((state) => state.thread.isLoading);

  useActiveSessionReadState(activeSessionId);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    const update = () => {
      setIsDesktop(media.matches);
      if (media.matches) setMobileDrawer(null);
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (isDesktop || !mobileDrawer) return;
    const drawer = mobileDrawer === "left" ? leftDrawerRef.current : rightDrawerRef.current;
    const trigger = mobileDrawer === "left" ? leftToggleRef.current : rightToggleRef.current;
    const focusFirst = () => drawer?.querySelector<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )?.focus();
    const frame = requestAnimationFrame(focusFirst);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileDrawer(null);
        requestAnimationFrame(() => trigger?.focus());
        return;
      }
      if (event.key !== "Tab" || !drawer) return;
      const focusable = [...drawer.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => element.offsetParent !== null);
      if (!focusable.length) {
        event.preventDefault();
        drawer.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isDesktop, mobileDrawer]);

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

  const leftOpen = isDesktop ? desktopLeftOpen : mobileDrawer === "left";
  const rightOpen = isDesktop ? desktopRightOpen : mobileDrawer === "right";
  const closeDrawer = (side: "left" | "right", restoreFocus = true) => {
    if (isDesktop) {
      if (side === "left") setDesktopLeftOpen(false);
      else setDesktopRightOpen(false);
    } else {
      setMobileDrawer(null);
    }
    if (restoreFocus) {
      requestAnimationFrame(() => {
        (side === "left" ? leftToggleRef : rightToggleRef).current?.focus();
      });
    }
  };
  const toggleDrawer = (side: "left" | "right") => {
    if (isDesktop) {
      if (side === "left") setDesktopLeftOpen((current) => !current);
      else setDesktopRightOpen((current) => !current);
      return;
    }
    setMobileDrawer((current) => current === side ? null : side);
  };
  const mobileModalOpen = !isDesktop && mobileDrawer !== null;

  return (
    <div className="chat-shell relative flex h-dvh overflow-hidden bg-background">
      <ChatSidebar
        disabled={isLoading || isThreadLoading}
        open={leftOpen}
        mobileMode={!isDesktop}
        drawerRef={leftDrawerRef}
        onClose={() => closeDrawer("left")}
        onNew={() => {
          setError(null);
          aui.threads.switchToNewThread();
          closeDrawer("left");
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
      <main
        id="chat-main-content"
        className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
        aria-hidden={mobileModalOpen}
        inert={mobileModalOpen}
      >
        <header className="chat-shell__header z-20 flex h-14 shrink-0 items-center justify-between gap-2 border-b px-3 sm:px-5">
          <Button
            ref={leftToggleRef}
            variant="ghost"
            size="icon"
            className="size-10 shrink-0"
            onClick={() => toggleDrawer("left")}
            aria-label={leftOpen ? "收起聊天记录" : "展开聊天记录"}
            aria-expanded={leftOpen}
            aria-controls="chat-history-drawer"
            title={leftOpen ? "收起聊天记录" : "展开聊天记录"}
          >
            {leftOpen ? <PanelLeftCloseIcon className="size-5" /> : <PanelLeftOpenIcon className="size-5" />}
          </Button>
          {error ? (
            <div role="alert" className="min-w-0 flex-1 truncate px-2 text-xs text-destructive">{error}</div>
          ) : <div className="min-w-0 flex-1" />}
          <Button
            ref={rightToggleRef}
            variant="ghost"
            size="icon"
            className={`size-10 shrink-0 ${process.env.NEXT_PUBLIC_DOTAMIND_TEST_OBSERVER_ENABLED === "true" ? "mr-12" : ""}`}
            onClick={() => toggleDrawer("right")}
            aria-label={rightOpen ? "收起会话 Trace" : "展开会话 Trace"}
            aria-expanded={rightOpen}
            aria-controls="session-trace-drawer"
            title={rightOpen ? "收起会话 Trace" : "展开会话 Trace"}
          >
            {rightOpen ? <PanelRightCloseIcon className="size-5" /> : <PanelRightOpenIcon className="size-5" />}
          </Button>
        </header>
        <div className="relative min-h-0 flex-1">
          <Thread browserId={browserId} />
        </div>
      </main>
      <SessionTracePanel
        browserId={browserId}
        open={rightOpen}
        mobileMode={!isDesktop}
        drawerRef={rightDrawerRef}
        onClose={() => closeDrawer("right")}
      />
      <TestObserverDrawer />
    </div>
  );
}
