"use client";

import {
  createContext,
  type FC,
  type PropsWithChildren,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { useAui, useAuiState } from "@assistant-ui/react";

import { Button } from "@/components/ui/button";
import { getApiUrl } from "@/lib/api-url";
import {
  resolveDisplayRefs,
  type ResolvedDisplayEntity,
} from "@/lib/entity-display-api";
import {
  displayMarkdownForCopy,
  entityForMarkdownReference,
  extractDisplayReferences,
} from "@/lib/entity-display-markdown";

const RESOLVE_MERGE_WINDOW_MS = 150;
const EntityDisplayContext = createContext<Readonly<Record<string, ResolvedDisplayEntity>>>({});

export const EntityDisplayMessage: FC<PropsWithChildren<{
  messageId: string;
  markdown: string;
  isComplete: boolean;
}>> = ({ messageId, markdown, isComplete, children }) => {
  const [entities, setEntities] = useState<Record<string, ResolvedDisplayEntity>>({});
  const attemptedRefs = useRef(new Set<string>());
  const pendingRefs = useRef(new Set<string>());
  const inFlight = useRef(false);
  const flushRequested = useRef(false);
  const activeController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const mergeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const drainQueue = useCallback(async () => {
    if (!mounted.current) return;
    flushRequested.current = true;
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      while (pendingRefs.current.size > 0 && mounted.current && flushRequested.current) {
        flushRequested.current = false;
        const batch = [...pendingRefs.current].slice(0, 100);
        for (const ref of batch) {
          pendingRefs.current.delete(ref);
          attemptedRefs.current.add(ref);
        }

        const controller = new AbortController();
        activeController.current = controller;
        try {
          const batchEntities = await resolveDisplayRefs(batch, controller.signal);
          if (mounted.current && !controller.signal.aborted) {
            setEntities((current) => ({ ...current, ...batchEntities }));
          }
        } catch {
          // Network failures are best-effort; aborted requests are requeued only
          // while this message remains mounted.
          if (controller.signal.aborted) {
            for (const ref of batch) {
              attemptedRefs.current.delete(ref);
              if (mounted.current) pendingRefs.current.add(ref);
            }
            // Strict Mode performs a development-only cleanup/setup cycle.
            // If that cycle aborted this request, drain the requeued batch.
            flushRequested.current = mounted.current;
          }
        } finally {
          if (activeController.current === controller) activeController.current = null;
        }
      }
    } finally {
      inFlight.current = false;
    }
  }, []);

  const queueReferences = useCallback((refs: readonly string[]) => {
    if (!mounted.current) return;
    for (const ref of refs) {
      if (attemptedRefs.current.has(ref)) continue;
      pendingRefs.current.add(ref);
    }
    if (pendingRefs.current.size === 0) return;
    if (mergeTimer.current) clearTimeout(mergeTimer.current);
    if (isComplete) {
      mergeTimer.current = null;
      void drainQueue();
    } else {
      mergeTimer.current = setTimeout(() => {
        mergeTimer.current = null;
        void drainQueue();
      }, RESOLVE_MERGE_WINDOW_MS);
    }
  }, [drainQueue, isComplete]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (mergeTimer.current) clearTimeout(mergeTimer.current);
      mergeTimer.current = null;
      activeController.current?.abort();
      activeController.current = null;
    };
  }, [messageId]);

  useEffect(() => {
    queueReferences(extractDisplayReferences(markdown));
  }, [isComplete, markdown, queueReferences]);

  return (
    <EntityDisplayContext.Provider value={entities}>
      {children}
    </EntityDisplayContext.Provider>
  );
};

export const EntityDisplayReference: FC<{
  "data-display-ref"?: string;
  children?: ReactNode;
}> = ({ "data-display-ref": displayRef, children }) => {
  const entities = useContext(EntityDisplayContext);
  const entity = displayRef ? entityForMarkdownReference(displayRef, entities) : undefined;
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);

  if (!entity) return <>{children}</>;

  const imageUrl = entity.image_url && failedImageUrl !== entity.image_url
    ? `${getApiUrl()}${entity.image_url}`
    : null;
  return (
    <span className="inline-flex max-w-full flex-wrap items-baseline gap-1 align-baseline">
      {imageUrl && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={imageUrl}
          alt=""
          aria-hidden="true"
          className="inline-block size-5 shrink-0 object-contain align-[-0.15em]"
          onError={() => setFailedImageUrl(entity.image_url)}
        />
      )}
      <span className="min-w-0 whitespace-normal break-words">{entity.label}</span>
    </span>
  );
};

export const EntityDisplayCopyButton: FC = () => {
  const aui = useAui();
  const entities = useContext(EntityDisplayContext);
  const isCopied = useAuiState((state) => state.message.isCopied);
  const hasText = useAuiState((state) => state.message.content.some(
    (part) => part.type === "text" && part.text.length > 0,
  ));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const copy = async () => {
    const source = aui.message.getCopyText();
    if (!source || typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(displayMarkdownForCopy(source, entities));
      aui.message.setIsCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        aui.message.setIsCopied(false);
        timer.current = null;
      }, 3000);
    } catch {
      aui.message.setIsCopied(false);
    }
  };

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-8"
      aria-label="复制回答"
      disabled={!hasText}
      onClick={() => void copy()}
    >
      {isCopied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
    </Button>
  );
};
