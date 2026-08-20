import type { LibraryFilters, SavedViewScope } from "@/types/domain"
import type { PipelineQueryArgs } from "./pipeline"

export const queryKeys = {
  schools: (filters: LibraryFilters, page: number, sort: string) => ["schools", filters, page, sort] as const,
  schoolsCount: (filters: LibraryFilters) => ["schools-count", filters] as const,
  school: (id: number) => ["school", id] as const,
  schoolContacts: (id: number) => ["school-contacts", id] as const,
  pipeline: (args: PipelineQueryArgs) => ["pipeline", args] as const,
  activity: (schoolId: number) => ["activity", schoolId] as const,
  enrichmentJobs: () => ["enrichment-jobs"] as const,
  enrichmentJob: (id: number) => ["enrichment-job", id] as const,
  dashboardSummary: () => ["dashboard-summary"] as const,
  dashboardActivity: (limit: number) => ["dashboard-activity", limit] as const,
  dashboardTopLeads: (limit: number) => ["dashboard-top-leads", limit] as const,
  savedViews: (scope: SavedViewScope) => ["saved-views", scope] as const,
  tags: () => ["tags"] as const,
  campaigns: () => ["campaigns"] as const,
  directory: (args: unknown) => ["directory", args] as const,
  campaign: (id: number) => ["campaign", id] as const,
  schoolTags: (schoolId: number) => ["school-tags", schoolId] as const,
  search: (q: string) => ["search", q] as const,
  queue: (limit: number) => ["pipeline-queue", limit] as const,
  pipelineMap: () => ["pipeline-map"] as const,
  autoEnrichSettings: () => ["auto-enrich-settings"] as const,
  funnelReport: () => ["funnel-report"] as const,
  dataQualityReport: () => ["data-quality-report"] as const,
}
