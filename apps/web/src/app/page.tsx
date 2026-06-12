import { Activity, BarChart3, Database, ShieldCheck } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { AskConsole } from "@/components/AskConsole";
import { HeroRankingTable } from "@/components/HeroRankingTable";
import { MetaScoreChart } from "@/components/MetaScoreChart";
import { MetricCard } from "@/components/MetricCard";
import { PatchImpactPanel } from "@/components/PatchImpactPanel";
import { ServiceCatalogPanel } from "@/components/ServiceCatalogPanel";
import { TeamReportPanel } from "@/components/TeamReportPanel";
import { getMetaReport, getPatchImpact, getServiceCatalog, getTeamReport } from "@/lib/api";

export default async function Home() {
  const [metaReport, patchImpact, teamReport, serviceCatalog] = await Promise.all([
    getMetaReport(),
    getPatchImpact(),
    getTeamReport(),
    getServiceCatalog(),
  ]);

  const topHero = metaReport.top_heroes[0];

  return (
    <AppShell>
      <div className="space-y-6">
        <AskConsole />

        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Report metrics">
          <MetricCard
            detail={`${topHero.hero} leads the sample offlane ranking.`}
            icon={BarChart3}
            label="Top hero"
            tone="primary"
            value={topHero.hero}
          />
          <MetricCard
            detail="Weighted from win rate, pick rate, pro presence, patch impact, and trend."
            icon={Activity}
            label="Meta score"
            tone="accent"
            value={`${topHero.meta_score}/100`}
          />
          <MetricCard
            detail="Report confidence is calculated from attached data signals."
            icon={ShieldCheck}
            label="Confidence"
            tone="success"
            value={`${Math.round(metaReport.confidence * 100)}%`}
          />
          <MetricCard
            detail="OpenDota, STRATZ, and official patch notes are represented in the contract."
            icon={Database}
            label="Sources"
            value={`${metaReport.sources.length}`}
          />
        </section>

        <div className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
          <HeroRankingTable heroes={metaReport.top_heroes} />
          <MetaScoreChart heroes={metaReport.top_heroes} />
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <PatchImpactPanel report={patchImpact} />
          <TeamReportPanel report={teamReport} />
        </div>

        <ServiceCatalogPanel catalog={serviceCatalog} />
      </div>
    </AppShell>
  );
}
