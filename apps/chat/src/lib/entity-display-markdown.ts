import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";

import {
  isDisplayReference,
  type ResolvedDisplayEntity,
} from "@/lib/entity-display-api";

type MarkdownPosition = {
  start?: { offset?: number };
  end?: { offset?: number };
};

type MarkdownNode = {
  type: string;
  url?: unknown;
  value?: unknown;
  alt?: unknown;
  children?: MarkdownNode[];
  position?: MarkdownPosition;
  data?: Record<string, unknown>;
};

export type DisplayLinkOccurrence = {
  displayRef: string;
  start: number;
  end: number;
  label: string;
  valid: boolean;
};

const parser = unified().use(remarkParse).use(remarkGfm);

/** Mark only AST link nodes as a safe non-link element for React rendering. */
export function remarkDisplayReferences() {
  return (tree: MarkdownNode) => {
    visitNodes(tree, (node) => {
      if (node.type !== "link" || typeof node.url !== "string" || !node.url.startsWith("display:")) {
        return;
      }
      node.data = {
        ...node.data,
        hName: "display-reference",
        hProperties: { "data-display-ref": node.url },
      };
      // Known mdast `link` nodes are always converted to <a> by
      // remark-rehype, which ignores hName. Turn the node into an unknown
      // inline node so its hName is honored and the display: URL never reaches
      // ReactMarkdown's link URL handling.
      node.type = "displayReference";
    });
  };
}

/** Extract complete display links from parsed Markdown, including GFM tables. */
export function displayLinksInMarkdown(source: string): DisplayLinkOccurrence[] {
  const tree = parser.parse(source) as unknown as MarkdownNode;
  const links: DisplayLinkOccurrence[] = [];
  visitNodes(tree, (node) => {
    if (node.type !== "link" || typeof node.url !== "string" || !node.url.startsWith("display:")) {
      return;
    }
    const start = node.position?.start?.offset;
    const end = node.position?.end?.offset;
    if (typeof start !== "number" || typeof end !== "number" || end <= start) return;
    links.push({
      displayRef: node.url,
      start,
      end,
      label: nodeChildrenText(node),
      valid: isDisplayReference(node.url),
    });
  });
  return links.sort((left, right) => left.start - right.start);
}

export function extractDisplayReferences(source: string): string[] {
  return [...new Set(
    displayLinksInMarkdown(source)
      .filter((link) => link.valid)
      .map((link) => link.displayRef),
  )];
}

/** Replace display-link syntax only; keep all other Markdown and code unchanged. */
export function displayMarkdownForCopy(
  source: string,
  entities: Readonly<Record<string, ResolvedDisplayEntity>>,
): string {
  const links = displayLinksInMarkdown(source);
  if (links.length === 0) return source;

  let cursor = 0;
  let result = "";
  for (const link of links) {
    if (link.start < cursor) continue;
    result += source.slice(cursor, link.start);
    result += link.valid ? (entities[link.displayRef]?.label ?? link.label) : link.label;
    cursor = link.end;
  }
  return result + source.slice(cursor);
}

export function entityForMarkdownReference(
  reference: string,
  entities: Readonly<Record<string, ResolvedDisplayEntity>>,
): ResolvedDisplayEntity | undefined {
  return isDisplayReference(reference) ? entities[reference] : undefined;
}

function visitNodes(node: MarkdownNode, visit: (node: MarkdownNode) => void): void {
  visit(node);
  for (const child of node.children ?? []) visitNodes(child, visit);
}

function nodeChildrenText(node: MarkdownNode): string {
  return (node.children ?? []).map((child) => {
    if (typeof child.value === "string") return child.value;
    if (typeof child.alt === "string") return child.alt;
    if (child.type === "break") return "\n";
    return nodeChildrenText(child);
  }).join("");
}
