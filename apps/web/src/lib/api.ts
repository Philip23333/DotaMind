import {
  metaReportMock,
  patchImpactMock,
  serviceCatalogMock,
  teamReportMock,
} from "@/lib/mock";
import type {
  MetaReport,
  NaturalLanguageQueryResponse,
  PatchImpactReport,
  ServiceCatalog,
  TeamReport,
} from "@/types/report";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
const EXPERIMENTAL_API_BASE_URL = process.env.NEXT_PUBLIC_EXPERIMENTAL_API_BASE_URL;

function requireEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} must be configured in .env`);
  }

  return value;
}

async function postJson<TResponse>(path: string, body: object, fallback: TResponse): Promise<TResponse> {
  try {
    const apiBaseUrl = requireEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE_URL);
    const response = await fetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    if (!response.ok) {
      return fallback;
    }

    return response.json() as Promise<TResponse>;
  } catch {
    return fallback;
  }
}

async function getJson<TResponse>(path: string, fallback: TResponse): Promise<TResponse> {
  try {
    const apiBaseUrl = requireEnv("NEXT_PUBLIC_API_BASE_URL", API_BASE_URL);
    const response = await fetch(`${apiBaseUrl}${path}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return fallback;
    }

    return response.json() as Promise<TResponse>;
  } catch {
    return fallback;
  }
}

export function getMetaReport(): Promise<MetaReport> {
  return postJson("/api/v1/meta-report", { game: "dota2", patch: "latest", role: "offlane" }, metaReportMock);
}

export function getPatchImpact(): Promise<PatchImpactReport> {
  return postJson("/api/v1/patch-impact", { game: "dota2", patch: "latest", role: "offlane" }, patchImpactMock);
}

export function getTeamReport(): Promise<TeamReport> {
  return postJson(
    "/api/v1/team-report",
    { game: "dota2", team_name: "Team Spirit", time_range: "last_30_days" },
    teamReportMock,
  );
}

export function getServiceCatalog(): Promise<ServiceCatalog> {
  return getJson("/api/v1/services", serviceCatalogMock);
}

export async function runExperimentalQuery(query: string): Promise<NaturalLanguageQueryResponse> {
  const browserApiBaseUrl = requireEnv(
    "NEXT_PUBLIC_EXPERIMENTAL_API_BASE_URL",
    EXPERIMENTAL_API_BASE_URL,
  );
  const response = await fetch(`${browserApiBaseUrl}/api/v1/query/experimental`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query, game: "dota2" }),
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`MetaMind API returned ${response.status}${detail ? `: ${detail}` : ""}`);
  }

  return response.json() as Promise<NaturalLanguageQueryResponse>;
}
