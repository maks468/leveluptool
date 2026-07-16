import { api } from "./client"
import type { AutoEnrichSettings } from "@/types/domain"

export interface ResetResult {
  school_contacts_removed: number
  enrichment_job_items_removed: number
  enrichment_jobs_removed: number
  school_tags_removed: number
  tags_removed: number
  activity_log_removed: number
  saved_views_removed: number
  pipeline_schools_removed: number
  schools_uncontacted_reset: number
}

export async function resetPipelineWorkflow(confirmation: string): Promise<ResetResult> {
  return api.post<ResetResult>("/admin/reset-pipeline", { confirmation })
}

export async function getAutoEnrichSettings(): Promise<AutoEnrichSettings> {
  return api.get<AutoEnrichSettings>("/admin/auto-enrich-settings")
}

export async function updateAutoEnrichSettings(
  patch: Partial<Pick<AutoEnrichSettings, "enabled" | "schools_per_run" | "interval_minutes">>
): Promise<AutoEnrichSettings> {
  return api.patch<AutoEnrichSettings>("/admin/auto-enrich-settings", patch)
}
