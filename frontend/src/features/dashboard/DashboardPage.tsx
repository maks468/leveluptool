import { useQuery } from "@tanstack/react-query"
import { Building2, Flame, GraduationCap, Users } from "lucide-react"
import { getDashboardSummary, getRecentActivity, getTopLeads } from "@/api/dashboard"
import { queryKeys } from "@/api/queryKeys"
import { StatCard } from "./components/StatCard"
import { StageBreakdown } from "./components/StageBreakdown"
import { RecentActivityFeed } from "./components/RecentActivityFeed"
import { TopLeadsList } from "./components/TopLeadsList"
import { PipelineMapCard } from "./components/PipelineMapCard"
import { AutoEnrichSettingsCard } from "./components/AutoEnrichSettingsCard"
import { ClearPipelineCard } from "./components/ClearPipelineCard"
import { ResetToolCard } from "./components/ResetToolCard"

export function DashboardPage() {
  const { data: summary } = useQuery({ queryKey: queryKeys.dashboardSummary(), queryFn: getDashboardSummary })
  const { data: activity = [] } = useQuery({
    queryKey: queryKeys.dashboardActivity(10),
    queryFn: () => getRecentActivity(10),
  })
  const { data: topLeads = [] } = useQuery({
    queryKey: queryKeys.dashboardTopLeads(10),
    queryFn: () => getTopLeads(10),
  })

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Dashboard</h1>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Available in Library"
          value={summary?.available_total ?? "—"}
          sublabel={summary ? `of ${summary.library_total.toLocaleString()} in register · ${summary.scored_total.toLocaleString()} scored` : undefined}
          icon={<Building2 className="h-4 w-4" />}
        />
        <StatCard
          label="In pipeline"
          value={summary?.pipeline_total ?? "—"}
          sublabel="Schools you're actively pursuing"
          icon={<Users className="h-4 w-4" />}
        />
        <StatCard
          label="High-score leads waiting"
          value={summary?.high_score_not_contacted ?? "—"}
          sublabel="Score 70+, not yet contacted"
          icon={<Flame className="h-4 w-4" />}
        />
        <StatCard
          label="In campaigns"
          value={summary?.campaign_schools_total ?? "—"}
          sublabel="Parked in outreach batches"
          icon={<GraduationCap className="h-4 w-4" />}
        />
      </div>

      <StageBreakdown stageCounts={summary?.stage_counts ?? {}} />

      <PipelineMapCard />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RecentActivityFeed entries={activity} />
        <TopLeadsList schools={topLeads} />
      </div>

      <AutoEnrichSettingsCard />

      <ClearPipelineCard />

      <ResetToolCard />
    </div>
  )
}
