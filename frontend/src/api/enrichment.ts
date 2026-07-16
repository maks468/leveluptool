import { api } from "./client"
import type { EnrichmentJob, LibraryFilters } from "@/types/domain"
import { filtersToApiBody } from "./schools"

export async function startEnrichmentJob(schoolIds: number[]): Promise<EnrichmentJob> {
  return api.post<EnrichmentJob>("/enrichment-jobs", { school_ids: schoolIds })
}

/** Enrich every school matching a Library filter set (highest score first),
 * optionally capped at `limit` -- the filter-based counterpart to
 * pullIntoPipeline, so "enrich all N matching" isn't bounded by page size. */
export async function startEnrichmentJobFromFilters(
  filters: LibraryFilters,
  limit: number | null
): Promise<EnrichmentJob> {
  return api.post<EnrichmentJob>("/enrichment-jobs", {
    filters: filtersToApiBody(filters),
    limit,
  })
}

/** All jobs, most recent first -- includes completed ones so the tray can
 * show a "done" summary before the user dismisses it (a job that's
 * already finished would otherwise never appear in a status-filtered
 * query). */
export async function listRecentJobs(): Promise<EnrichmentJob[]> {
  return api.get<EnrichmentJob[]>("/enrichment-jobs")
}

export async function getJob(id: number): Promise<EnrichmentJob> {
  return api.get<EnrichmentJob>(`/enrichment-jobs/${id}`)
}
