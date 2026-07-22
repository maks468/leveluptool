import { api, API_BASE_URL } from "./client"
import type {
  ActivityLogEntry,
  EnrichmentLevel,
  LibraryFilters,
  MapSchool,
  PipelineListResponse,
  PipelineSchool,
  PipelineStage,
  QueueEntry,
} from "@/types/domain"
import { filtersToApiBody } from "./schools"

export interface PipelineQueryArgs {
  page?: number
  pageSize?: number
  stage?: PipelineStage
  q?: string
  voivodeship?: string | null
  city?: string | null
  tagId?: number | null
  scoreMin?: number | null
  scoreMax?: number | null
  scoreIncludeUnscored?: boolean
  enrichmentLevel?: EnrichmentLevel | null
  sort?: string
}

function pipelineQueryParams(args: PipelineQueryArgs): URLSearchParams {
  const { stage, q, voivodeship, city, tagId, scoreMin, scoreMax, scoreIncludeUnscored = true, enrichmentLevel } = args
  const params = new URLSearchParams()
  if (stage) params.set("stage", stage)
  if (q) params.set("q", q)
  if (voivodeship) params.set("voivodeship", voivodeship)
  if (city) params.set("city", city)
  if (tagId !== null && tagId !== undefined) params.set("tag_id", String(tagId))
  if (scoreMin !== null && scoreMin !== undefined) params.set("score_min", String(scoreMin))
  if (scoreMax !== null && scoreMax !== undefined) params.set("score_max", String(scoreMax))
  params.set("score_include_unscored", String(scoreIncludeUnscored))
  if (enrichmentLevel) params.set("enrichment_level", enrichmentLevel)
  return params
}

export async function listPipeline(args: PipelineQueryArgs = {}): Promise<PipelineListResponse> {
  const { page = 1, pageSize = 50, sort } = args
  const params = pipelineQueryParams(args)
  params.set("page", String(page))
  params.set("page_size", String(pageSize))
  if (sort) params.set("sort", sort)
  return api.get<PipelineListResponse>(`/pipeline?${params.toString()}`)
}

/** All school ids in the pipeline matching these filters, across every
 * page -- so an action can cover the whole filtered view (e.g. "enrich
 * all") rather than just the schools on the current page. */
export async function listPipelineIds(args: PipelineQueryArgs = {}): Promise<number[]> {
  const params = pipelineQueryParams(args)
  const { ids } = await api.get<{ ids: number[] }>(`/pipeline/ids?${params.toString()}`)
  return ids
}

/** CSV export is a plain navigation (not a fetch call) so the browser
 * handles the Content-Disposition download itself -- same pattern as the
 * Library's exportSchoolsCsvUrl. */
export function exportPipelineCsvUrl(args: PipelineQueryArgs = {}): string {
  const params = pipelineQueryParams(args)
  if (args.sort) params.set("sort", args.sort)
  return `${API_BASE_URL}/pipeline/export?${params.toString()}`
}

export async function pullIntoPipeline(
  args: { schoolIds?: number[]; filters?: LibraryFilters; limit?: number | null }
): Promise<{ pulled_new: number; already_in_pipeline: number }> {
  const body = args.schoolIds
    ? { school_ids: args.schoolIds }
    : { filters: args.filters ? filtersToApiBody(args.filters) : {}, limit: args.limit ?? null }
  return api.post("/pipeline/pull", body)
}

export async function setStage(schoolId: number, stage: PipelineStage): Promise<PipelineSchool> {
  return api.patch<PipelineSchool>(`/schools/${schoolId}/stage`, { stage })
}

export async function getActivity(schoolId: number): Promise<ActivityLogEntry[]> {
  return api.get<ActivityLogEntry[]>(`/schools/${schoolId}/activity`)
}

export async function addActivityNote(schoolId: number, note: string): Promise<ActivityLogEntry> {
  return api.post<ActivityLogEntry>(`/schools/${schoolId}/activity`, { note })
}

export async function setFollowUp(
  schoolId: number,
  args: { next_action_note: string | null; next_action_date: string | null }
): Promise<PipelineSchool> {
  return api.patch<PipelineSchool>(`/schools/${schoolId}/follow-up`, args)
}

export async function listQueue(limit = 50): Promise<QueueEntry[]> {
  return api.get<QueueEntry[]>(`/pipeline/queue?limit=${limit}`)
}

export async function getMapSchools(): Promise<MapSchool[]> {
  return api.get<MapSchool[]>("/pipeline/map")
}

export async function bulkSetStage(schoolIds: number[], stage: PipelineStage): Promise<{ updated: number }> {
  return api.patch("/pipeline/bulk-stage", { school_ids: schoolIds, stage })
}
