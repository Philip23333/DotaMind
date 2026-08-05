"use client";

import {
  ThreadListItemPrimitive,
  ThreadListPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import { useEffect, useRef, useState } from "react";
import {
  CheckIcon,
  MessageSquareIcon,
  MoreHorizontalIcon,
  PinIcon,
  PinOffIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
  XIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";

type ChatSidebarProps = {
  unreadRunCountBySession?: Record<string, number>;
  disabled?: boolean;
  mobileOpen?: boolean;
  onClose?: () => void;
  onNew: () => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onPin: (sessionId: string, isPinned: boolean) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
};

export function ChatSidebar({
  unreadRunCountBySession = {},
  disabled = false,
  mobileOpen = false,
  onClose,
  onNew,
  onRename,
  onPin,
  onDelete,
}: ChatSidebarProps) {
  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-black/30 md:hidden"
          aria-label="关闭聊天列表"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[min(86vw,18rem)] shrink-0 flex-col border-r bg-background shadow-xl transition-transform md:static md:z-auto md:w-72 md:translate-x-0 md:bg-muted/20 md:shadow-none ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="聊天列表"
      >
        <div className="flex items-center justify-between border-b px-3 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <MessageSquareIcon className="size-4" />
            <span>聊天记录</span>
          </div>
          <div className="flex items-center gap-1">
            <ThreadListPrimitive.New
              disabled={disabled}
              onClick={onNew}
              render={
                <Button variant="outline" size="icon" className="size-10" aria-label="新建聊天" />
              }
            >
              <PlusIcon className="size-4" />
            </ThreadListPrimitive.New>
            <Button
              variant="ghost"
              size="icon"
              className="size-10 md:hidden"
              onClick={onClose}
              aria-label="关闭聊天列表"
            >
              <XIcon className="size-4" />
            </Button>
          </div>
        </div>

        <ThreadListPrimitive.Root className="min-h-0 flex-1 overflow-y-auto p-2">
          <div className="flex flex-col gap-1">
            <ThreadListPrimitive.Items>
              {({ threadListItem }) => {
                const remoteId = threadListItem.remoteId;
                if (!remoteId) return null;
                return (
                  <ChatSidebarItem
                    key={threadListItem.id}
                    remoteId={remoteId}
                    title={threadListItem.title ?? "新聊天"}
                    isPinned={threadListItem.custom?.isPinned === true}
                    unreadCount={unreadRunCountBySession[remoteId] ?? 0}
                    disabled={disabled}
                    onClose={onClose}
                    onRename={onRename}
                    onPin={onPin}
                    onDelete={onDelete}
                  />
                );
              }}
            </ThreadListPrimitive.Items>
          </div>
        </ThreadListPrimitive.Root>
      </aside>
    </>
  );
}

function ChatSidebarItem({
  remoteId,
  title,
  isPinned,
  unreadCount,
  disabled,
  onClose,
  onRename,
  onPin,
  onDelete,
}: {
  remoteId: string;
  title: string;
  isPinned: boolean;
  unreadCount: number;
  disabled: boolean;
  onClose?: () => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onPin: (sessionId: string, isPinned: boolean) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
}) {
  const active = useAuiState((state) => state.threads.mainThreadId === state.threadListItem.id);
  const [editing, setEditing] = useState(false);
  const [editingTitle, setEditingTitle] = useState(title);
  const [menuOpen, setMenuOpen] = useState(false);
  const [savingRename, setSavingRename] = useState(false);
  const cancelRename = useRef(false);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const focusMenu = requestAnimationFrame(() => menuRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    };
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || menuButtonRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      cancelAnimationFrame(focusMenu);
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [menuOpen]);

  const saveRename = async () => {
    const nextTitle = editingTitle.trim();
    if (!nextTitle || savingRename) return;
    setSavingRename(true);
    try {
      await onRename(remoteId, nextTitle);
      setEditing(false);
    } finally {
      setSavingRename(false);
    }
  };

  return (
    <ThreadListItemPrimitive.Root
      className={`group relative flex min-h-11 items-center gap-1 rounded-xl px-2 py-1.5 ${
        active ? "bg-accent" : "hover:bg-accent/60"
      }`}
    >
      {editing ? (
        <input
          autoFocus
          value={editingTitle}
          disabled={savingRename}
          onChange={(event) => setEditingTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void saveRename();
            if (event.key === "Escape") {
              cancelRename.current = true;
              setEditing(false);
            }
          }}
          className="min-w-0 flex-1 rounded-md border bg-background px-2 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/30"
          aria-label="聊天标题"
        />
      ) : (
        <ThreadListItemPrimitive.Trigger
          disabled={disabled}
          onClick={onClose}
          className="flex min-w-0 flex-1 items-center gap-1.5 px-1 py-2 text-left text-sm"
        >
          {isPinned && <PinIcon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />}
          <span className="min-w-0 truncate">{title}</span>
          {!!unreadCount && (
            <span className="ml-auto rounded-full bg-primary px-1.5 text-[10px] leading-5 text-primary-foreground">
              {unreadCount}
            </span>
          )}
        </ThreadListItemPrimitive.Trigger>
      )}

      {editing ? (
        <Button
          variant="ghost"
          size="icon"
          className="size-10"
          onClick={() => void saveRename()}
          disabled={savingRename}
          aria-label="保存标题"
        >
          <CheckIcon className="size-4" />
        </Button>
      ) : (
        <>
          <Button
            ref={menuButtonRef}
            variant="ghost"
            size="icon"
            className="size-10 shrink-0"
            onClick={() => setMenuOpen((current) => !current)}
            disabled={disabled}
            aria-label={`聊天“${title}”更多操作`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
          >
            <MoreHorizontalIcon className="size-4" />
          </Button>
          {menuOpen && (
            <div
              ref={menuRef}
              tabIndex={-1}
              role="menu"
              aria-label={`聊天“${title}”操作`}
              className="absolute right-2 top-full z-10 mt-1 flex min-w-36 flex-col rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
            >
              <button
                type="button"
                role="menuitem"
                className="flex min-h-11 items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-accent focus:bg-accent focus:outline-none"
                onClick={() => {
                  setMenuOpen(false);
                  void onPin(remoteId, !isPinned);
                }}
              >
                {isPinned ? <PinOffIcon className="size-4" /> : <PinIcon className="size-4" />}
                {isPinned ? "取消置顶" : "置顶聊天"}
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex min-h-11 items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-accent focus:bg-accent focus:outline-none"
                onClick={() => {
                  setMenuOpen(false);
                  cancelRename.current = false;
                  setEditingTitle(title);
                  setEditing(true);
                }}
              >
                <PencilIcon className="size-4" />
                重命名
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex min-h-11 items-center gap-2 rounded-md px-3 text-left text-sm text-destructive hover:bg-destructive/10 focus:bg-destructive/10 focus:outline-none"
                onClick={() => {
                  setMenuOpen(false);
                  if (window.confirm(`删除“${title}”？此操作不可恢复。`)) void onDelete(remoteId);
                }}
              >
                <Trash2Icon className="size-4" />
                删除
              </button>
            </div>
          )}
        </>
      )}
    </ThreadListItemPrimitive.Root>
  );
}
