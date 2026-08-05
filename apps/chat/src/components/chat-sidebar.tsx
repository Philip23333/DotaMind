"use client";

import { Button } from "@/components/ui/button";
import type { ChatSessionSummary } from "@/lib/dotamind-api";
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
import { useEffect, useRef, useState } from "react";

type ChatSidebarProps = {
  sessions: ChatSessionSummary[];
  activeSessionId: string;
  unreadRunCountBySession?: Record<string, number>;
  disabled?: boolean;
  mobileOpen?: boolean;
  onClose?: () => void;
  onNew: () => void;
  onSelect: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onPin: (sessionId: string, isPinned: boolean) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
};

export function ChatSidebar({
  sessions,
  activeSessionId,
  unreadRunCountBySession = {},
  disabled = false,
  mobileOpen = false,
  onClose,
  onNew,
  onSelect,
  onRename,
  onPin,
  onDelete,
}: ChatSidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);
  const [savingRename, setSavingRename] = useState(false);
  const cancelRename = useRef(false);
  const menuButtonRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuId) return;
    const focusMenu = requestAnimationFrame(() => menuRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setMenuId(null);
      menuButtonRefs.current[menuId]?.focus();
    };
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      const menuButton = menuButtonRefs.current[menuId];
      if (menuRef.current?.contains(target) || menuButton?.contains(target)) return;
      setMenuId(null);
    };
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      cancelAnimationFrame(focusMenu);
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [menuId]);

  const startRename = (session: ChatSessionSummary) => {
    setMenuId(null);
    cancelRename.current = false;
    setEditingId(session.session_id);
    setEditingTitle(session.title);
  };

  const saveRename = async () => {
    if (!editingId || !editingTitle.trim() || savingRename) return;
    setSavingRename(true);
    try {
      await onRename(editingId, editingTitle.trim());
      setEditingId(null);
    } finally {
      setSavingRename(false);
    }
  };

  const cancelEditing = () => {
    cancelRename.current = true;
    setEditingId(null);
  };

  const removeSession = async (session: ChatSessionSummary) => {
    setMenuId(null);
    if (!window.confirm(`删除“${session.title}”？此操作不可恢复。`)) return;
    await onDelete(session.session_id);
  };

  const togglePin = async (session: ChatSessionSummary) => {
    setMenuId(null);
    await onPin(session.session_id, !session.is_pinned);
  };

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
            <Button
              variant="outline"
              size="icon"
              className="size-10"
              onClick={onNew}
              disabled={disabled}
              aria-label="新建聊天"
            >
              <PlusIcon className="size-4" />
            </Button>
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

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <div className="flex flex-col gap-1">
            {sessions.map((session) => {
              const active = session.session_id === activeSessionId;
              const editing = session.session_id === editingId;
              const menuOpen = session.session_id === menuId;
              return (
                <div
                  key={session.session_id}
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
                      onBlur={(event) => {
                        const next = event.relatedTarget as Node | null;
                        if (!cancelRename.current && !event.currentTarget.parentElement?.contains(next)) {
                          void saveRename();
                        }
                        cancelRename.current = false;
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void saveRename();
                        if (event.key === "Escape") cancelEditing();
                      }}
                      className="min-w-0 flex-1 rounded-md border bg-background px-2 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/30"
                      aria-label="聊天标题"
                    />
                  ) : (
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-center gap-1.5 px-1 py-2 text-left text-sm"
                      onClick={() => {
                        onSelect(session.session_id);
                        onClose?.();
                      }}
                      disabled={disabled}
                    >
                      {session.is_pinned && (
                        <PinIcon
                          className="size-3.5 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      )}
                      <span className="min-w-0 truncate">{session.title}</span>
                      {!!unreadRunCountBySession[session.session_id] && (
                        <span className="ml-auto rounded-full bg-primary px-1.5 text-[10px] leading-5 text-primary-foreground">
                          {unreadRunCountBySession[session.session_id]}
                        </span>
                      )}
                    </button>
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
                        ref={(element) => {
                          menuButtonRefs.current[session.session_id] = element;
                        }}
                        variant="ghost"
                        size="icon"
                        className="size-10 shrink-0"
                        onClick={() => setMenuId(menuOpen ? null : session.session_id)}
                        disabled={disabled}
                        aria-label={`聊天“${session.title}”更多操作`}
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
                          aria-label={`聊天“${session.title}”操作`}
                          className="absolute right-2 top-full z-10 mt-1 flex min-w-36 flex-col rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg"
                        >
                          <button
                            type="button"
                            role="menuitem"
                            className="flex min-h-11 items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-accent focus:bg-accent focus:outline-none"
                            onClick={() => void togglePin(session)}
                          >
                            {session.is_pinned ? (
                              <PinOffIcon className="size-4" />
                            ) : (
                              <PinIcon className="size-4" />
                            )}
                            {session.is_pinned ? "取消置顶" : "置顶聊天"}
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="flex min-h-11 items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-accent focus:bg-accent focus:outline-none"
                            onClick={() => startRename(session)}
                          >
                            <PencilIcon className="size-4" />
                            重命名
                          </button>
                          <button
                            type="button"
                            role="menuitem"
                            className="flex min-h-11 items-center gap-2 rounded-md px-3 text-left text-sm text-destructive hover:bg-destructive/10 focus:bg-destructive/10 focus:outline-none"
                            onClick={() => void removeSession(session)}
                          >
                            <Trash2Icon className="size-4" />
                            删除
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </aside>
    </>
  );
}
