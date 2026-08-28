import { getApiUrl } from "./api-url";

export type CatalogVisualEntity = {
  kind: "hero" | "item" | "ability" | "team";
  imagePath: string;
  label: string;
  names: string[];
};

export type CatalogVisualPayload = {
  catalog_visual_entities?: CatalogVisualEntity[];
  tool_results?: Array<{ data?: unknown }>;
};

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
  payload: CatalogVisualPayload,
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

function replaceFinalInventoryItemNamesWithIcons(
  value: string,
  items: CatalogVisualEntity[],
): string {
  const labels = [...value.matchAll(/主装备：|背包：|中立：|强化：/g)];
  if (!labels.length) return replaceEntityNamesWithIcons(value, items, "lg");

  return labels
    .map((label, index) => {
      const start = label.index ?? 0;
      const contentStart = start + label[0].length;
      const contentEnd = labels[index + 1]?.index ?? value.length;
      const size: CatalogIconSize = label[0] === "主装备：" ? "lg" : "md";
      const content = value.slice(contentStart, contentEnd).replace(/[（）()]/g, "");
      return replaceEntityNamesWithIcons(content, items, size);
    })
    .filter(Boolean)
    .join("");
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
  let playerProgressSubsection:
    | "starting_items"
    | "final_inventory"
    | "build"
    | "ability"
    | null = null;
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
        if (/^\*\*出门装\*\*/.test(line)) {
          playerProgressSubsection = "starting_items";
        } else if (/^\*\*最终装备\*\*/.test(line)) {
          playerProgressSubsection = "final_inventory";
        } else if (/^\*\*出装路径\*\*/.test(line)) {
          playerProgressSubsection = "build";
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
        if (playerProgressSubsection === "starting_items") {
          return replaceEntityNamesWithIcons(
            line,
            entities.filter((entity) => entity.kind === "item"),
            "lg",
          );
        }
        if (playerProgressSubsection === "final_inventory") {
          return replaceFinalInventoryItemNamesWithIcons(
            line,
            entities.filter((entity) => entity.kind === "item"),
          );
        }
        if (playerProgressSubsection === "build") {
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
