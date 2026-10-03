import { getApiUrl } from "./api-url";

export type RecentSeriesCandidate = {
  series_id: number;
  name: string | null;
  league_name: string | null;
  lifecycle: "running" | "past";
  begin_at: string | null;
  end_at: string | null;
  champion_name: string | null;
};

export type RecentSeriesResponse = {
  status: "fresh" | "stale" | "unavailable";
  items: RecentSeriesCandidate[];
  retrieved_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
};

const INVALID_RESPONSE = "近期赛事响应无效。";

function isNullableText(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableDate(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && Number.isFinite(Date.parse(value)));
}

function isRecentSeriesCandidate(value: unknown): value is RecentSeriesCandidate {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.series_id === "number" &&
    Number.isSafeInteger(candidate.series_id) &&
    candidate.series_id > 0 &&
    isNullableText(candidate.name) &&
    (candidate.league_name === undefined || isNullableText(candidate.league_name)) &&
    (candidate.lifecycle === "running" || candidate.lifecycle === "past") &&
    isNullableDate(candidate.begin_at) &&
    isNullableDate(candidate.end_at) &&
    isNullableText(candidate.champion_name)
  );
}

function isRecentSeriesResponse(value: unknown): value is RecentSeriesResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const response = value as Record<string, unknown>;
  return (
    (response.status === "fresh" || response.status === "stale" || response.status === "unavailable") &&
    Array.isArray(response.items) &&
    response.items.every(isRecentSeriesCandidate) &&
    isNullableDate(response.retrieved_at) &&
    isNullableDate(response.last_attempt_at) &&
    isNullableText(response.last_error)
  );
}

export async function getRecentSeries(signal?: AbortSignal): Promise<RecentSeriesResponse> {
  let response: Response;
  try {
    response = await fetch(`${getApiUrl()}/api/v1/home/recent-series`, {
      method: "GET",
      cache: "no-store",
      ...(signal ? { signal } : {}),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error("赛事列表暂时不可用。");
  }

  if (!response.ok) throw new Error("赛事列表暂时不可用。");

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(INVALID_RESPONSE);
  }

  if (!isRecentSeriesResponse(payload)) throw new Error(INVALID_RESPONSE);
  return {
    ...payload,
    items: payload.items.map((item) => ({ ...item, league_name: item.league_name ?? null })),
  };
}

export function recentSeriesDisplayName(series: Pick<RecentSeriesCandidate, "name" | "league_name">): string {
  const leagueName = series.league_name?.trim();
  const seriesName = series.name?.trim();
  if (leagueName) return `${leagueName} · ${seriesName || "未命名赛事"}`;
  return seriesName || "未命名赛事";
}
