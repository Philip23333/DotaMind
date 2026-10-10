// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EntityDisplayMessage, EntityDisplayReference } from "@/components/entity-display";
import {
  extractDisplayReferences,
  remarkDisplayReferences,
} from "@/lib/entity-display-markdown";

const ref = "display:valve:hero:14";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("entity display message", () => {
  it("renders display links through a safe custom AST element, not an anchor", () => {
    const markdown = `[帕吉](${ref})`;
    const { container } = render(
      <ReactMarkdown
        remarkPlugins={[remarkDisplayReferences]}
        components={{
          "display-reference": (props: { children?: ReactNode; "data-display-ref"?: string }) => (
            <span data-rendered-ref={props["data-display-ref"]}>{props.children}</span>
          ),
        } as never}
      >
        {markdown}
      </ReactMarkdown>,
    );

    expect(container.querySelector("a[href^='display:']")).toBeNull();
    expect(container.querySelector("[data-rendered-ref]")?.getAttribute("data-rendered-ref")).toBe(ref);
    expect(screen.getByText("帕吉")).toBeTruthy();
  });

  it("keeps the source label until resolution, merges for 150ms, and hides a broken local image", async () => {
    const requestedUrls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      requestedUrls.push(String(input));
      return new Response(JSON.stringify({
        entities: {
          [ref]: {
            display_ref: ref,
            kind: "hero",
            label: "帕吉最新名称",
            image_url: `/api/v1/assets/dota/by-hash/${"b".repeat(64)}.png`,
          },
        },
      }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <EntityDisplayMessage messageId="assistant-1" markdown={`[原名称](${ref})`} isComplete={false}>
        <EntityDisplayReference data-display-ref={ref}>原名称</EntityDisplayReference>
      </EntityDisplayMessage>,
    );

    expect(extractDisplayReferences(`[原名称](${ref})`)).toEqual([ref]);
    expect(screen.getByText("原名称")).toBeTruthy();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 175)); });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestedUrls).toEqual(["http://localhost:8001/api/v1/display/resolve"]);
    expect(container.querySelector("a[href^='display:']")).toBeNull();
    expect(screen.getByText("帕吉最新名称")).toBeTruthy();
    const image = container.querySelector("img");
    expect(image?.getAttribute("alt")).toBe("");
    expect(image?.getAttribute("src")).toBe(
      `http://localhost:8001/api/v1/assets/dota/by-hash/${"b".repeat(64)}.png`,
    );

    if (image) fireEvent.error(image);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("帕吉最新名称")).toBeTruthy();
  });

  it("cancels an in-flight lookup when the message unmounts", async () => {
    const signals: Array<AbortSignal | undefined> = [];
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      signals.push(init?.signal as AbortSignal | undefined);
      return new Promise<Response>(() => undefined);
    }));

    const rendered = render(
      <EntityDisplayMessage messageId="assistant-2" markdown={`[帕吉](${ref})`} isComplete>
        <EntityDisplayReference data-display-ref={ref}>帕吉</EntityDisplayReference>
      </EntityDisplayMessage>,
    );
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 175)); });
    rendered.unmount();

    expect(signals[0]?.aborted).toBe(true);
  });

  it("requeues an aborted lookup when the message remains mounted after an effect cleanup", async () => {
    let callCount = 0;
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      callCount += 1;
      if (callCount === 1) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          }, { once: true });
        });
      }
      return Promise.resolve(new Response(JSON.stringify({
        entities: {
          [ref]: {
            display_ref: ref,
            kind: "hero",
            label: "帕吉最新名称",
            image_url: null,
          },
        },
      }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const rendered = render(
      <StrictMode>
        <EntityDisplayMessage messageId="assistant-strict" markdown={`[帕吉](${ref})`} isComplete>
          <EntityDisplayReference data-display-ref={ref}>帕吉</EntityDisplayReference>
        </EntityDisplayMessage>
      </StrictMode>,
    );

    expect(await screen.findByText("帕吉最新名称")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);

    rendered.rerender(
      <StrictMode>
        <EntityDisplayMessage messageId="assistant-strict" markdown={`[新标签](${ref})`} isComplete>
          <EntityDisplayReference data-display-ref={ref}>新标签</EntityDisplayReference>
        </EntityDisplayMessage>
      </StrictMode>,
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("drains all batches for a complete history message without another render", async () => {
    const refs = Array.from({ length: 101 }, (_, index) => `display:valve:item:${index + 1}`);
    const batchSizes: number[] = [];
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { refs: string[] };
      batchSizes.push(body.refs.length);
      const entities = Object.fromEntries(body.refs.map((displayRef) => [displayRef, {
        display_ref: displayRef,
        kind: "item",
        label: `Resolved ${displayRef}`,
        image_url: null,
      }]));
      return new Response(JSON.stringify({ entities }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <EntityDisplayMessage
        messageId="assistant-history-101"
        markdown={refs.map((displayRef) => `[source](${displayRef})`).join("\n")}
        isComplete
      >
        {refs.map((displayRef) => (
          <EntityDisplayReference key={displayRef} data-display-ref={displayRef}>
            source
          </EntityDisplayReference>
        ))}
      </EntityDisplayMessage>,
    );

    expect(await screen.findByText("Resolved display:valve:item:101")).toBeTruthy();
    expect(batchSizes).toEqual([100, 1]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("continues to the next batch after a failed batch without retrying the first", async () => {
    const refs = Array.from({ length: 101 }, (_, index) => `display:valve:item:${index + 1}`);
    const batchSizes: number[] = [];
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { refs: string[] };
      batchSizes.push(body.refs.length);
      if (batchSizes.length === 1) return new Response("unavailable", { status: 503 });
      const entities = Object.fromEntries(body.refs.map((displayRef) => [displayRef, {
        display_ref: displayRef,
        kind: "item",
        label: `Resolved ${displayRef}`,
        image_url: null,
      }]));
      return new Response(JSON.stringify({ entities }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(
      <EntityDisplayMessage
        messageId="assistant-history-failed-batch"
        markdown={refs.map((displayRef) => `[source](${displayRef})`).join("\n")}
        isComplete
      >
        {refs.map((displayRef, index) => (
          <EntityDisplayReference key={displayRef} data-display-ref={displayRef}>
            {`Fallback ${index + 1}`}
          </EntityDisplayReference>
        ))}
      </EntityDisplayMessage>,
    );

    expect(await screen.findByText("Resolved display:valve:item:101")).toBeTruthy();
    expect(container.textContent).toContain("Fallback 1");
    expect(batchSizes).toEqual([100, 1]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps readable text after lookup failure and does not retry the same reference", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 503 }));
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(
      <EntityDisplayMessage messageId="assistant-3" markdown={`[帕吉](${ref})`} isComplete>
        <EntityDisplayReference data-display-ref={ref}>帕吉</EntityDisplayReference>
      </EntityDisplayMessage>,
    );

    expect(await screen.findByText("帕吉")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    rerender(
      <EntityDisplayMessage messageId="assistant-3" markdown={`[帕吉](${ref}) 再次出现`} isComplete>
        <EntityDisplayReference data-display-ref={ref}>帕吉</EntityDisplayReference>
      </EntityDisplayMessage>,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("帕吉")).toBeTruthy();
  });
});
