import {
  metaReportMock,
  patchImpactMock,
  serviceCatalogMock,
  teamReportMock,
} from "@/lib/mock";
import type { MetaReport, PatchImpactReport, ServiceCatalog, TeamReport } from "@/types/report";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function postJson<TResponse>(path: string, body: object, fallback: TResponse): Promise<TResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
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
    const response = await fetch(`${API_BASE_URL}${path}`, {
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
