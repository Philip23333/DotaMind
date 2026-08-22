import type { ThreadMessage, ThreadMessageLike } from "@assistant-ui/react";

import { createUuidV4 } from "./uuid";
import { formatToolFailure, isToolFailureCode } from "./runtime-failure";

const DEFAULT_API_URL = "http://localhost:8001";
export const BROWSER_ID_STORAGE_KEY = "dotamind.browser_id.v1";
export const ACTIVE_SESSION_STORAGE_KEY = "dotamind.active_session_id.v1";

export type PlanStatus =
  | "ok"
  | "clarification_required"
  | "insufficient_context"
  | "insufficient_tools"
  | "insufficient_evidence"
  | "error";

type AnswerItem = Record<string, unknown>;
type ToolResultPayload = {
  data?: unknown;
};

export type CatalogVisualEntity = {
  kind: "hero" | "item" | "ability" | "team";
  imagePath: string;
  label: string;
  names: string[];
};

export type RuntimeToolCallStatus = {
  tool_call_id: string;
  tool: string;
  status: "ok" | "error";
  latency_ms: number;
  reused: boolean;
  handler_entered: boolean;
  dispatch_stage: string;
  failure_code: string | null;
};

type RuntimeAttempt = {
  tool_call_statuses?: RuntimeToolCallStatus[];
};

export type PlanResponse = {
  status?: PlanStatus;
  reason?: string;
  error_code?: string | null;
  runtime?: { duration_ms?: number; attempts?: RuntimeAttempt[] };
  catalog_visual_entities?: CatalogVisualEntity[];
  tool_results?: ToolResultPayload[];
  answer?: {
    summary?: string;
    claims?: AnswerItem[];
    recommendations?: AnswerItem[];
    limitations?: AnswerItem[];
  } | null;
};

export type ChatSessionSummary = {
  session_id: string;
  game: "dota2";
  title: string;
  title_is_custom: boolean;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
  active_run?: ChatRunSummary | null;
};

export type ChatRunStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "waiting_input"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export type ChatRunCheckpointOption = {
  id: string;
  label: string;
  value: Record<string, unknown>;
};

export type ChatRunCheckpoint = {
  checkpoint_type: string;
  question: string;
  options: ChatRunCheckpointOption[];
  source_tool_call_id: string;
  resume_node: "controller" | "tools";
};

export type ChatRunSummary = {
  run_id: string;
  session_id: string;
  request_id: string;
  status: ChatRunStatus;
  user_query: string;
  last_event_sequence: number;
  result_turn_id: string | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  heartbeat_at: string | null;
  cancel_requested_at: string | null;
  completed_at: string | null;
};

export type ChatTranscriptTurn = {
  turn_index: number;
  request_id: string;
  user_query: string;
  public_response: PlanResponse;
  created_at: string;
};

export type ChatSessionResponse = {
  session: ChatSessionSummary;
  turns: ChatTranscriptTurn[];
};

export type PlanStreamEvent =
  | {
      type: "phase";
      phase: "planning" | "tool_execution" | "answering" | "reviewing";
      attempt_index: number;
    }
  | {
      type: "tool";
      tool_call_id: string;
      tool: string;
      attempt_index: number;
      status: "running" | "ok" | "error";
      latency_ms: number | null;
      reused: boolean | null;
      failure_code: string | null;
      handler_entered?: boolean | null;
      dispatch_stage?: string | null;
    }
  | {
      type: "observer";
      kind: "model_prompt" | "model_output" | "tool_input" | "tool_output";
      stage: "controller" | "answer" | "tool";
      call_id: string;
      name: string;
      attempt_index: number;
      payload: Record<string, unknown>;
    }
  | { type: "answer_delta"; delta: string; attempt_index: number; provisional: true }
  | { type: "result"; response: PlanResponse; session?: ChatSessionSummary | null }
  | { type: "error"; error_code: string; reason: string }
  | { type: "checkpoint"; checkpoint: ChatRunCheckpoint }
  | {
      type: "status";
      status: ChatRunStatus;
      error_code?: string | null;
      transcript_recovery?: boolean;
    };

export function getApiUrl(): string {
  return (process.env.NEXT_PUBLIC_DOTAMIND_API_URL ?? DEFAULT_API_URL).replace(
    /\/$/,
    "",
  );
}

export function getOrCreateBrowserId(): string {
  if (typeof window === "undefined") return createUuidV4();
  const existing = window.localStorage.getItem(BROWSER_ID_STORAGE_KEY);
  if (existing) return existing;
  const created = createUuidV4();
  window.localStorage.setItem(BROWSER_ID_STORAGE_KEY, created);
  return created;
}

export function getStoredActiveSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
}

export function storeActiveSessionId(sessionId: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
  }
}

export function clearStoredActiveSessionId(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  }
}

function browserHeaders(browserId: string, includeJson = false): HeadersInit {
  return {
    ...(includeJson ? { "Content-Type": "application/json" } : {}),
    "X-DotaMind-Browser-Id": browserId,
  };
}

async function readResponseError(response: Response): Promise<Error> {
  try {
    const payload = (await response.json()) as { reason?: string };
    return new Error(payload.reason?.trim() || `DotaMind API 请求失败（HTTP ${response.status}）。`);
  } catch {
    return new Error(`DotaMind API 请求失败（HTTP ${response.status}）。`);
  }
}

export async function listChatSessions(browserId: string): Promise<ChatSessionSummary[]> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions`, {
    headers: browserHeaders(browserId),
  });
  if (!response.ok) throw await readResponseError(response);
  const payload = (await response.json()) as { sessions: ChatSessionSummary[] };
  return payload.sessions;
}

export async function createChatSession(browserId: string): Promise<ChatSessionSummary> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions`, {
    method: "POST",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({ game: "dota2" }),
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionSummary;
}

export async function getChatSession(
  browserId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<ChatSessionResponse> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    headers: browserHeaders(browserId),
    signal,
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionResponse;
}

export async function renameChatSession(
  browserId: string,
  sessionId: string,
  title: string,
): Promise<ChatSessionSummary> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({ title }),
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionSummary;
}

export async function setChatSessionPinned(
  browserId: string,
  sessionId: string,
  isPinned: boolean,
): Promise<ChatSessionSummary> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    method: "PATCH",
    headers: browserHeaders(browserId, true),
    body: JSON.stringify({ is_pinned: isPinned }),
  });
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ChatSessionSummary;
}

export async function deleteChatSession(browserId: string, sessionId: string): Promise<void> {
  const response = await fetch(`${getApiUrl()}/api/v1/chat/sessions/${sessionId}`, {
    method: "DELETE",
    headers: browserHeaders(browserId),
  });
  if (!response.ok) throw await readResponseError(response);
}

export function transcriptToInitialMessages(
  session: ChatSessionResponse,
): ThreadMessageLike[] {
  return session.turns.flatMap((turn) => [
    {
      id: `${session.session.session_id}:user:${turn.turn_index}`,
      role: "user" as const,
      content: [{ type: "text" as const, text: turn.user_query }],
      createdAt: new Date(turn.created_at),
    },
    {
      id: `${session.session.session_id}:assistant:${turn.turn_index}`,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: formatPlanResponse(turn.public_response) }],
      status: { type: "complete" as const, reason: "stop" as const },
      createdAt: new Date(turn.created_at),
    },
  ]);
}

export function pendingRunToInitialMessages(run: ChatRunSummary): ThreadMessageLike[] {
  return [
    {
      id: `${run.run_id}:user`,
      role: "user" as const,
      content: [{ type: "text" as const, text: run.user_query }],
    },
    {
      id: `${run.run_id}:assistant`,
      role: "assistant" as const,
      content: [{ type: "text" as const, text: "正在恢复分析运行…" }],
    },
  ];
}

export function latestUserText(messages: readonly ThreadMessage[]): string {
  const message = messages.findLast((item) => item.role === "user");

  return (
    message?.content
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("\n")
      .trim() ?? ""
  );
}

function stringField(item: AnswerItem, key: string): string | null {
  const value = item[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function formatRecommendations(items: AnswerItem[] | undefined): string | null {
  if (!items?.length) return null;

  const lines = items.flatMap((item) => {
    const subject = stringField(item, "subject");
    const rationale = stringField(item, "rationale");
    if (!subject && !rationale) return [];
    if (subject && rationale) return [`- **${subject}**：${rationale}`];
    return [`- ${subject ?? rationale}`];
  });

  return lines.length ? `### 建议\n\n${lines.join("\n")}` : null;
}

function formatClaims(items: AnswerItem[] | undefined): string | null {
  if (!items?.length) return null;

  const lines = items
    .map((item) => stringField(item, "claim"))
    .filter((claim): claim is string => claim !== null)
    .map((claim) => `- ${claim}`);

  return lines.length ? `### 依据\n\n${lines.join("\n")}` : null;
}

function formatLimitations(items: AnswerItem[] | undefined): string | null {
  if (!items?.length) return null;

  const lines = items
    .map((item) => stringField(item, "detail"))
    .filter((detail): detail is string => detail !== null)
    .map((detail) => `- ${detail}`);

  return lines.length ? `### 注意\n\n${lines.join("\n")}` : null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

const LOCAL_ASSET_PREFIX = "/api/v1/assets/";

function localAssetPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.startsWith(LOCAL_ASSET_PREFIX) &&
    /\.(?:png|jpe?g|webp)$/i.test(value)
  );
}

function catalogKindFromPath(
  imagePath: string,
): CatalogVisualEntity["kind"] | null {
  if (imagePath.includes("/heroes/")) return "hero";
  if (imagePath.includes("/items/")) return "item";
  if (imagePath.includes("/abilities/")) return "ability";
  if (imagePath.includes("/esports/teams/")) return "team";
  return null;
}

function nonEmptyStrings(values: unknown[]): string[] {
  return Array.from(
    new Set(
      values
        .filter((value): value is string => typeof value === "string")
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  );
}

function collectFieldNames(
  record: Record<string, unknown>,
  kind: CatalogVisualEntity["kind"] | null,
  includeGenericNames = false,
): { names: string[]; label: string | null } {
  const fields = [
    kind === "hero"
      ? "hero_name_zh"
      : kind === "item"
        ? "item_name_zh"
        : "name_zh",
    kind === "hero"
      ? "hero_name_en"
      : kind === "item"
        ? "item_name_en"
        : "name_en",
    ...(includeGenericNames ? ["name_zh", "name_en", "name", "acronym"] : []),
  ];
  const names = nonEmptyStrings(fields.map((field) => record[field]));
  return { names, label: names[0] ?? null };
}

export function extractCatalogVisualEntities(
  payload: PlanResponse,
): CatalogVisualEntity[] {
  if (payload.catalog_visual_entities) {
    return payload.catalog_visual_entities.filter((entity) =>
      isLocalVisualEntity(entity),
    );
  }
  const byImagePath = new Map<string, CatalogVisualEntity>();
  const labelRank = new Map<string, number>();

  const addEntity = (
    imagePath: string,
    kind: CatalogVisualEntity["kind"],
    names: string[],
    label: string | null,
    rank: number,
  ) => {
    if (!names.length) return;
    const existing = byImagePath.get(imagePath);
    if (!existing) {
      byImagePath.set(imagePath, {
        kind,
        imagePath,
        label: label ?? (kind === "hero" ? "英雄" : "物品"),
        names: [...names].sort((left, right) => right.length - left.length),
      });
      labelRank.set(imagePath, rank);
      return;
    }
    existing.names = nonEmptyStrings([...existing.names, ...names]).sort(
      (left, right) => right.length - left.length,
    );
    if (label && rank < (labelRank.get(imagePath) ?? Number.MAX_SAFE_INTEGER)) {
      existing.label = label;
      labelRank.set(imagePath, rank);
    }
  };

  const visit = (value: unknown) => {
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item));
      return;
    }
    const record = asRecord(value);
    if (!record) return;

    const heroImagePath = localAssetPath(record.hero_image_path)
      ? record.hero_image_path
      : null;
    const itemImagePath = localAssetPath(record.item_image_path)
      ? record.item_image_path
      : null;
    if (heroImagePath) {
      const { names, label } = collectFieldNames(record, "hero");
      addEntity(heroImagePath, "hero", names, label, 0);
    }
    if (itemImagePath) {
      const { names, label } = collectFieldNames(record, "item");
      addEntity(itemImagePath, "item", names, label, 0);
    }
    const abilityImagePath = localAssetPath(record.ability_image_path)
      ? record.ability_image_path
      : null;
    if (abilityImagePath) {
      const { names, label } = collectFieldNames(record, "ability", true);
      addEntity(abilityImagePath, "ability", names, label, 0);
    }
    const teamImagePath = localAssetPath(record.team_image_path)
      ? record.team_image_path
      : null;
    if (teamImagePath) {
      const { names, label } = collectFieldNames(record, "team", true);
      addEntity(teamImagePath, "team", names, label, 0);
    }

    if (localAssetPath(record.image_path)) {
      const kind = catalogKindFromPath(record.image_path);
      if (kind !== null) {
        const { names, label } = collectFieldNames(record, kind, true);
        addEntity(record.image_path, kind, names, label, 1);
      }
    }

    Object.values(record).forEach((child) => visit(child));
  };

  (payload.tool_results ?? []).forEach((toolResult) => visit(toolResult.data));
  return [...byImagePath.values()];
}

function isLocalVisualEntity(entity: CatalogVisualEntity): boolean {
  return catalogKindFromPath(entity.imagePath) === entity.kind && localAssetPath(entity.imagePath);
}

type TextRange = [start: number, end: number];

function protectedMarkdownRanges(line: string): TextRange[] {
  const ranges: TextRange[] = [];
  const addMatches = (pattern: RegExp) => {
    for (const match of line.matchAll(pattern)) {
      const start = match.index ?? 0;
      ranges.push([start, start + match[0].length]);
    }
  };
  addMatches(/`+[^`]*`+/g);
  addMatches(/!?\[[^\]]*\]\([^)]*\)/g);
  return ranges.sort((left, right) => left[0] - right[0]);
}

function rangeAt(ranges: TextRange[], index: number): TextRange | null {
  return ranges.find(([start, end]) => index >= start && index < end) ?? null;
}

function isTableSeparator(line: string): boolean {
  return /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function isTableRow(line: string): boolean {
  return /^\s*\|.*\|\s*$/.test(line) && !isTableSeparator(line);
}

type CatalogIconSize = "sm" | "md" | "lg";

function smallHeading(line: string): boolean {
  return /(?:\bbp\b|\bpick\b|\bban\b|阵容|出装|购买顺序|加点|天赋)/i.test(line);
}

function hasCatalogImageBefore(line: string, index: number): boolean {
  return /!\[[^\]]*\]\([^)]*\/api\/v1\/assets\/[^)]*#dota-size=(?:sm|md|lg)\)\s*$/.test(
    line.slice(0, index),
  );
}

function catalogImageMarkdown(
  entity: CatalogVisualEntity,
  size: CatalogIconSize,
): string {
  return `![${entity.label}](${getApiUrl()}${entity.imagePath}#dota-size=${size})`;
}

function decorateCatalogLine(
  line: string,
  entities: CatalogVisualEntity[],
  size: CatalogIconSize,
): string {
  if (!entities.length || isTableSeparator(line)) return line;
  const ranges = protectedMarkdownRanges(line);
  const replacements: Array<{ index: number; name: string; entity: CatalogVisualEntity }> = [];
  let index = 0;
  let previous: { entity: CatalogVisualEntity; end: number } | null = null;

  while (index < line.length) {
    const protectedRange = rangeAt(ranges, index);
    if (protectedRange) {
      index = protectedRange[1];
      continue;
    }
    const matches = entities.flatMap((entity) =>
      entity.names
        .filter((name) => line.startsWith(name, index))
        .map((name) => ({ entity, name })),
    );
    const match = matches.sort((left, right) => right.name.length - left.name.length)[0];
    if (!match) {
      index += 1;
      continue;
    }
    const aliasSeparator =
      previous?.entity.imagePath === match.entity.imagePath &&
      /^[\s（）()［］\[\]{}:：,，./·—–\-]*$/u.test(line.slice(previous.end, index));
    if (!aliasSeparator && !hasCatalogImageBefore(line, index)) {
      replacements.push({ index, name: match.name, entity: match.entity });
      previous = { entity: match.entity, end: index + match.name.length };
    }
    index += match.name.length;
  }

  return replacements
    .reverse()
    .reduce((result, replacement) => {
      return `${result.slice(0, replacement.index)}${catalogImageMarkdown(replacement.entity, size)}${result.slice(replacement.index)}`;
    }, line);
}

function markdownTableCells(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) return null;
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((cell) => cell.trim());
}

function renderMarkdownTableCells(cells: string[]): string {
  return `| ${cells.join(" | ")} |`;
}

function equipmentColumnIndex(cells: string[]): number | null {
  const index = cells.findIndex((cell) => /^(?:核心)?装备$/.test(cell));
  return index === -1 ? null : index;
}

function playerHeroColumnIndex(cells: string[]): number | null {
  const index = cells.findIndex((cell) => /^选手\s*\/\s*英雄$/.test(cell));
  return index === -1 ? null : index;
}

function isDraftOrderHeader(cells: string[]): boolean {
  return (
    cells.length === 8 &&
    cells[0] === "顺序" &&
    cells.slice(1).every((cell, index) => cell === String(index + 1))
  );
}

function isDraftActionRow(cells: string[]): boolean {
  return cells.length === 8 && (cells[0] === "选择" || cells[0] === "禁用");
}

function replaceEntityNamesWithIcons(
  value: string,
  entities: CatalogVisualEntity[],
  size: CatalogIconSize,
): string {
  if (!entities.length) return value;
  const replacements: Array<{ index: number; name: string; entity: CatalogVisualEntity }> = [];
  let index = 0;
  while (index < value.length) {
    const matches = entities.flatMap((entity) =>
      entity.names
        .filter((name) => value.startsWith(name, index))
        .map((name) => ({ entity, name })),
    );
    const match = matches.sort((left, right) => right.name.length - left.name.length)[0];
    if (!match) {
      index += 1;
      continue;
    }
    replacements.push({ index, name: match.name, entity: match.entity });
    index += match.name.length;
  }
  if (!replacements.length) return value;

  let output = "";
  let cursor = 0;
  for (const replacement of replacements) {
    const between = value.slice(cursor, replacement.index);
    if (!/^[\s,，、；;/·]*$/u.test(between)) output += between;
    output += catalogImageMarkdown(replacement.entity, size);
    cursor = replacement.index + replacement.name.length;
  }
  const tail = value.slice(cursor);
  if (!/^[\s,，、；;/·]*$/u.test(tail)) output += tail;
  return output;
}

function replaceLabeledEquipmentItemNames(
  value: string,
  items: CatalogVisualEntity[],
): string {
  const labels = [...value.matchAll(/主装备：|背包：|中立：|强化：/g)];
  if (!labels.length) return replaceEntityNamesWithIcons(value, items, "md");

  let output = "";
  let cursor = 0;
  for (const [index, label] of labels.entries()) {
    const start = label.index ?? 0;
    const contentStart = start + label[0].length;
    const contentEnd = labels[index + 1]?.index ?? value.length;
    const prefix = value.slice(cursor, label[0] === "主装备：" ? contentStart : start);
    output += label[0] === "强化：" ? prefix : prefix.replace(/[；;]\s*$/u, "");
    output += replaceEntityNamesWithIcons(
      value.slice(contentStart, contentEnd),
      items,
      label[0] === "主装备：" ? "md" : "sm",
    );
    cursor = contentEnd;
  }
  return output;
}

function decoratePlayerHeroCell(value: string, heroes: CatalogVisualEntity[]): string {
  const separator = " · ";
  const separatorIndex = value.indexOf(separator);
  if (separatorIndex === -1) return decorateCatalogLine(value, heroes, "md");
  const playerPrefixEnd = separatorIndex + separator.length;
  const heroText = value.slice(playerPrefixEnd);
  const decoratedHeroText = decorateCatalogLine(heroText, heroes, "md");
  if (decoratedHeroText === heroText) return value;
  const icon = decoratedHeroText.slice(0, decoratedHeroText.length - heroText.length);
  return icon ? `${icon}${value}` : decoratedHeroText;
}

export function decorateCatalogMentions(
  markdown: string | null | undefined,
  entities: CatalogVisualEntity[],
): string | null {
  if (!markdown || !entities.length) return markdown ?? null;
  const lines = markdown.split("\n");
  let inFence = false;
  let compactHeadingLevel: number | null = null;
  let playerProgressHeadingLevel: number | null = null;
  let playerProgressSubsection: "item" | "ability" | null = null;
  let activeEquipmentColumn: number | null = null;
  let activePlayerHeroColumn: number | null = null;
  let activeDraftTable = false;
  return lines
    .map((line) => {
      if (/^\s*(```|~~~)/.test(line)) {
        inFence = !inFence;
        return line;
      }
      if (inFence) return line;
      if (isTableSeparator(line)) return line;
      if (isTableRow(line)) {
        const cells = markdownTableCells(line);
        const headerEquipmentColumn = cells ? equipmentColumnIndex(cells) : null;
        if (headerEquipmentColumn !== null) {
          activeEquipmentColumn = headerEquipmentColumn;
          activePlayerHeroColumn = playerHeroColumnIndex(cells ?? []);
          activeDraftTable = false;
          return line;
        }
        if (cells && isDraftOrderHeader(cells)) {
          activeEquipmentColumn = null;
          activePlayerHeroColumn = null;
          activeDraftTable = true;
          return line;
        }
        if (cells && activeDraftTable && isDraftActionRow(cells)) {
          return renderMarkdownTableCells([
            cells[0],
            ...cells.slice(1).map((cell) =>
              replaceEntityNamesWithIcons(
                cell,
                entities.filter((entity) => entity.kind === "hero"),
                "lg",
              ),
            ),
          ]);
        }
        if (cells && activeEquipmentColumn !== null && activeEquipmentColumn < cells.length) {
          const heroEntities = entities.filter((entity) => entity.kind === "hero");
          const decoratedCells =
            activePlayerHeroColumn === null
              ? markdownTableCells(decorateCatalogLine(line, heroEntities, "sm"))
              : [...cells];
          if (!decoratedCells) return line;
          if (
            activePlayerHeroColumn !== null &&
            activePlayerHeroColumn < decoratedCells.length
          ) {
            decoratedCells[activePlayerHeroColumn] = decoratePlayerHeroCell(
              decoratedCells[activePlayerHeroColumn],
              heroEntities,
            );
          }
          decoratedCells[activeEquipmentColumn] = replaceLabeledEquipmentItemNames(
            decoratedCells[activeEquipmentColumn],
            entities.filter((entity) => entity.kind === "item"),
          );
          return renderMarkdownTableCells(decoratedCells);
        }
        activeEquipmentColumn = null;
        activePlayerHeroColumn = null;
        activeDraftTable = false;
        return decorateCatalogLine(line, entities, "sm");
      }
      activeEquipmentColumn = null;
      activePlayerHeroColumn = null;
      activeDraftTable = false;
      const heading = line.match(/^(#{1,6})\s+/);
      if (heading) {
        const level = heading[1].length;
        if (/出装、加点与天赋/.test(line)) {
          playerProgressHeadingLevel = level;
          playerProgressSubsection = null;
        } else if (
          playerProgressHeadingLevel !== null &&
          level <= playerProgressHeadingLevel
        ) {
          playerProgressHeadingLevel = null;
          playerProgressSubsection = null;
        }
        if (smallHeading(line)) {
          compactHeadingLevel = level;
        } else if (compactHeadingLevel !== null && level <= compactHeadingLevel) {
          compactHeadingLevel = null;
        }
      }
      if (playerProgressHeadingLevel !== null) {
        if (/^\*\*(?:出门装|最终装备|出装路径)\*\*/.test(line)) {
          playerProgressSubsection = "item";
        } else if (/^\*\*技能加点\*\*/.test(line)) {
          playerProgressSubsection = "ability";
        } else if (/^\*\*天赋选择\*\*/.test(line)) {
          playerProgressSubsection = null;
        }
        if (playerProgressSubsection === "ability") {
          return decorateCatalogLine(
            line,
            entities.filter((entity) => entity.kind === "ability"),
            "md",
          );
        }
        if (playerProgressSubsection === "item") {
          return decorateCatalogLine(
            line,
            entities.filter((entity) => entity.kind === "item"),
            "md",
          );
        }
        return line;
      }
      const inCompactHeading = compactHeadingLevel !== null;
      const size = heading?.[1] === "#"
          ? inCompactHeading
            ? "sm"
            : "lg"
          : inCompactHeading
            ? "sm"
            : "md";
      return decorateCatalogLine(line, entities, size);
    })
    .join("\n");
}

export function formatPlanResponse(payload: PlanResponse): string {
  const runtimeFailure = payload.runtime?.attempts
    ?.flatMap((attempt) => attempt.tool_call_statuses ?? [])
    .find((tool) => tool.status === "error" && tool.failure_code)?.failure_code;
  const reason = payload.reason?.trim();
  const shouldUseRuntimeFailure = Boolean(
    runtimeFailure &&
      !payload.answer?.summary?.trim() &&
      (!reason || ["tool execution failed", "execution failed"].includes(reason)),
  );
  const summaryOrReason = payload.answer?.summary?.trim() || payload.reason?.trim();
  const sections = [
    summaryOrReason,
    formatRecommendations(payload.answer?.recommendations),
    formatClaims(payload.answer?.claims),
    formatLimitations(payload.answer?.limitations),
  ].filter((section): section is string => Boolean(section));
  const answerText = sections.join("\n\n");
  const formattedAnswer =
    payload.status === "ok"
      ? decorateCatalogMentions(answerText, extractCatalogVisualEntities(payload))
      : answerText;

  if (formattedAnswer && !shouldUseRuntimeFailure) return formattedAnswer;

  if (shouldUseRuntimeFailure && isToolFailureCode(runtimeFailure)) {
    return formatToolFailure(runtimeFailure);
  }

  if (payload.error_code) {
    if (isToolFailureCode(payload.error_code)) return formatToolFailure(payload.error_code);
    return reason || `请求未能完成（${payload.error_code}），请稍后重试。`;
  }

  return "请求已完成，但服务没有返回可展示的回答。";
}

export function formatStreamError(errorCode: string, reason: string): string {
  const message = isToolFailureCode(errorCode)
    ? formatToolFailure(errorCode)
    : reason || "请求未能完成，请稍后重试。";
  return `${message}\n\n错误代码：\`${errorCode}\``;
}
