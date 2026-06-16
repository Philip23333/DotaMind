export type Verdict =
  | "supported"
  | "partially_supported"
  | "weakly_supported"
  | "unsupported";

export interface Source {
  name: string;
  kind: string;
  url?: string | null;
  status: string;
}

export interface EvidenceItem {
  signal: string;
  verdict: Verdict;
  detail: string;
  source: string;
}

export interface HeroRecommendation {
  hero: string;
  role: string;
  win_rate: number;
  pick_rate: number;
  ban_rate: number;
  pro_presence: number;
  meta_score: number;
  confidence: number;
  recommendation: string;
  reasons: string[];
  practice_advice: string[];
  evidence: EvidenceItem[];
}

export interface MetaReport {
  report_type: "meta_report";
  game: "dota2";
  patch: string;
  role: string;
  summary: string;
  top_heroes: HeroRecommendation[];
  sources: Source[];
  analysis_steps: string[];
  confidence: number;
}

export interface PatchImpactReport {
  report_type: "patch_impact";
  game: "dota2";
  patch: string;
  summary: string;
  winners: string[];
  losers: string[];
  item_impacts: string[];
  lineup_trends: string[];
  practice_advice: string[];
  sources: Source[];
  confidence: number;
}

export interface TeamReport {
  report_type: "team_report";
  game: "dota2";
  team_name: string;
  time_range: string;
  summary: string;
  recent_record: string;
  signature_heroes: string[];
  draft_preferences: string[];
  win_patterns: string[];
  loss_patterns: string[];
  patch_adaptation_score: number;
  key_players: string[];
  sources: Source[];
  confidence: number;
}

export interface ServiceDescriptor {
  name: string;
  endpoint: string;
  price_usdc: number;
  description: string;
  input_schema: Record<string, string>;
}

export interface ServiceCatalog {
  services: ServiceDescriptor[];
  commerce_status: string;
  notes: string[];
}

export interface PlannedTask {
  agent: string;
  action: string;
  status: string;
}

export type QueryReport = MetaReport | PatchImpactReport | TeamReport;

export interface NaturalLanguageQueryResponse {
  query: string;
  routed_service: string;
  tasks: PlannedTask[];
  result: QueryReport;
}
