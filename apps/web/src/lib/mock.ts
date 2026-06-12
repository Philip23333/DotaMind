import type { MetaReport, PatchImpactReport, ServiceCatalog, TeamReport } from "@/types/report";

const sources = [
  {
    name: "OpenDota",
    kind: "public_api",
    url: "https://docs.opendota.com/",
    status: "mocked",
  },
  {
    name: "STRATZ",
    kind: "graphql_api",
    url: "https://stratz.com/api",
    status: "planned",
  },
  {
    name: "Dota2 Patch Notes",
    kind: "official_patch_notes",
    url: "https://www.dota2.com/patches/",
    status: "planned",
  },
];

export const metaReportMock: MetaReport = {
  report_type: "meta_report",
  game: "dota2",
  patch: "latest",
  role: "offlane",
  summary:
    "Sample offlane report ranks heroes by win rate, pick rate, pro presence, patch impact, and trend signals.",
  confidence: 0.57,
  sources,
  analysis_steps: [
    "Normalize role and patch request.",
    "Collect hero statistics from configured data sources.",
    "Calculate MVP meta score using weighted signals.",
    "Attach evidence labels and confidence.",
    "Return a structured report for web and agent callers.",
  ],
  top_heroes: [
    {
      hero: "Beastmaster",
      role: "offlane",
      win_rate: 0.531,
      pick_rate: 0.142,
      ban_rate: 0.188,
      pro_presence: 0.43,
      meta_score: 69,
      confidence: 0.65,
      recommendation: "S",
      reasons: [
        "High pro draft presence compared with other offlaners.",
        "Stable high-MMR win rate with rising pick rate.",
        "Fits fast objective pressure and summon-based map control.",
      ],
      practice_advice: [
        "Practice early Helm timing routes.",
        "Review lane matchups against ranged carries.",
        "Coordinate first Roshan and tower pressure windows.",
      ],
      evidence: [
        {
          signal: "High-MMR win rate",
          verdict: "supported",
          detail: "Sample win rate is 53.1%.",
          source: "OpenDota",
        },
        {
          signal: "Professional draft presence",
          verdict: "supported",
          detail: "Sample pro presence is 43.0%.",
          source: "STRATZ",
        },
      ],
    },
    {
      hero: "Underlord",
      role: "offlane",
      win_rate: 0.527,
      pick_rate: 0.118,
      ban_rate: 0.091,
      pro_presence: 0.28,
      meta_score: 58,
      confidence: 0.54,
      recommendation: "A",
      reasons: [
        "Reliable laning keeps draft execution stable.",
        "Auras and area control punish melee-heavy lineups.",
        "Lower ban rate makes it easier to practice consistently.",
      ],
      practice_advice: [
        "Practice wave cutting without overextending.",
        "Track aura item timing versus enemy physical cores.",
      ],
      evidence: [
        {
          signal: "High-MMR win rate",
          verdict: "supported",
          detail: "Sample win rate is 52.7%.",
          source: "OpenDota",
        },
      ],
    },
    {
      hero: "Mars",
      role: "offlane",
      win_rate: 0.506,
      pick_rate: 0.103,
      ban_rate: 0.124,
      pro_presence: 0.35,
      meta_score: 50,
      confidence: 0.51,
      recommendation: "A-",
      reasons: [
        "Still valuable in pro drafts because Arena creates reliable fight shape.",
        "Pairs well with common burst supports.",
        "Win rate is moderate, so execution quality matters.",
      ],
      practice_advice: [
        "Drill Spear angles around river and jungle entrances.",
        "Coordinate Arena cooldown with smoke and rune timings.",
      ],
      evidence: [
        {
          signal: "Professional draft presence",
          verdict: "partially_supported",
          detail: "Sample pro presence is 35.0%.",
          source: "STRATZ",
        },
      ],
    },
  ],
};

export const patchImpactMock: PatchImpactReport = {
  report_type: "patch_impact",
  game: "dota2",
  patch: "latest",
  summary:
    "The current sample patch rewards offlaners that create early map pressure, buy team auras, or force structured fights.",
  winners: ["Beastmaster", "Underlord", "Dark Seer"],
  losers: ["Greedy melee offlaners", "Slow blink-only initiators"],
  item_impacts: [
    "Aura builders gain value when teams group earlier.",
    "Summon tempo items support faster tower pressure.",
    "Expensive greed items are riskier when lanes collapse early.",
  ],
  lineup_trends: [
    "Earlier five-man moves around offlane tower pressure.",
    "Flexible initiation from position 3 and 4.",
    "Heroes that reveal or control large areas gain value.",
  ],
  practice_advice: [
    "Prioritize two or three offlaners with different initiation profiles.",
    "Review first 12 minutes and objective timing instead of only KDA.",
  ],
  confidence: 0.68,
  sources,
};

export const teamReportMock: TeamReport = {
  report_type: "team_report",
  game: "dota2",
  team_name: "Team Spirit",
  time_range: "last_30_days",
  summary:
    "Team Spirit's sample profile shows strong patch adaptation through flexible cores, stable late-game calls, and high-value comfort heroes.",
  recent_record: "7-3 in tracked sample matches",
  signature_heroes: ["Puck", "Collapse Mars", "Mira Rubick", "Yatoro Morphling"],
  draft_preferences: [
    "Flexible opening picks that hide core lanes.",
    "Teamfight control paired with scaling carry options.",
    "Comfort heroes preserved until later draft phases.",
  ],
  win_patterns: [
    "Stabilize lanes, trade objectives, then win second Roshan fights.",
    "Use mid-game smoke timing around vision denial.",
  ],
  loss_patterns: [
    "Can be punished by early tempo drafts before core item timings.",
    "Drafts with limited tower damage may stall after winning fights.",
  ],
  patch_adaptation_score: 82,
  key_players: ["Yatoro", "Larl", "Collapse"],
  sources,
  confidence: 0.72,
};

export const serviceCatalogMock: ServiceCatalog = {
  commerce_status: "CAP integration planned; pricing is exposed for the MVP service contract.",
  notes: [
    "Basic meta report is priced at 0.1 USDC.",
    "Team intelligence report is priced at 0.3 USDC.",
    "Deep patch impact report is priced at 0.5 USDC.",
  ],
  services: [
    {
      name: "get_meta_report",
      endpoint: "/api/v1/meta-report",
      price_usdc: 0.1,
      description: "Returns ranked heroes for a game, patch, and role.",
      input_schema: { game: "dota2", patch: "latest | patch id", role: "offlane" },
    },
    {
      name: "get_team_report",
      endpoint: "/api/v1/team-report",
      price_usdc: 0.3,
      description: "Returns recent professional team intelligence.",
      input_schema: { game: "dota2", team_name: "Team Spirit", time_range: "last_30_days" },
    },
    {
      name: "get_patch_impact",
      endpoint: "/api/v1/patch-impact",
      price_usdc: 0.5,
      description: "Returns winners, losers, item impacts, and lineup trends for a patch.",
      input_schema: { game: "dota2", patch: "latest", role: "optional role filter" },
    },
  ],
};
