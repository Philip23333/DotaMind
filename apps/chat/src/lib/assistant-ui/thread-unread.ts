import { useCallback, useEffect, useSyncExternalStore } from "react";

import {
  clearStoredActiveSessionId,
  getStoredActiveSessionId,
  storeActiveSessionId,
} from "@/lib/dotamind-api";

export const DOTAMIND_THREAD_METADATA_EVENT = "dotamind:thread-metadata-updated";
const UNREAD_STORAGE_KEY = "dotamind.thread_unread.v1";
const NO_UNREAD = 0;

function subscribeToUnreadChanges(listener: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener(DOTAMIND_THREAD_METADATA_EVENT, listener);
  return () => window.removeEventListener(DOTAMIND_THREAD_METADATA_EVENT, listener);
}

function readUnread(): Record<string, number> {
  if (typeof window === "undefined") return {};
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(UNREAD_STORAGE_KEY) ?? "{}");
    if (!value || typeof value !== "object") return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        ([, count]) => typeof count === "number" && Number.isFinite(count) && count > 0,
      ),
    );
  } catch {
    return {};
  }
}

function writeUnread(unread: Record<string, number>): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(UNREAD_STORAGE_KEY, JSON.stringify(unread));
  window.dispatchEvent(new Event(DOTAMIND_THREAD_METADATA_EVENT));
}

export function getSessionUnreadCount(sessionId: string): number {
  return readUnread()[sessionId] ?? 0;
}

export function useSessionUnreadCount(sessionId: string): number {
  const getSnapshot = useCallback(() => getSessionUnreadCount(sessionId), [sessionId]);
  return useSyncExternalStore(subscribeToUnreadChanges, getSnapshot, () => NO_UNREAD);
}

export function useActiveSessionReadState(sessionId: string | null | undefined): void {
  useEffect(() => {
    if (sessionId) {
      storeActiveSessionId(sessionId);
      markDotaMindSessionRead(sessionId);
    } else {
      clearStoredActiveSessionId();
    }
  }, [sessionId]);
}

export function markDotaMindSessionUnread(sessionId: string): void {
  if (getStoredActiveSessionId() === sessionId) return;
  const unread = readUnread();
  unread[sessionId] = (unread[sessionId] ?? 0) + 1;
  writeUnread(unread);
}

export function markDotaMindSessionRead(sessionId: string): void {
  const unread = readUnread();
  if (!(sessionId in unread)) return;
  delete unread[sessionId];
  writeUnread(unread);
}
