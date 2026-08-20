import { api } from "./client"
import type {
  CityFacet,
  DirectoryListResponse,
  FacetScope,
  LibraryFilters,
  School,
  SchoolContact,
  SchoolListResponse,
  VoivodeshipFacet,
} from "@/types/domain"

export function filtersToParams(filters: LibraryFilters): Record<string, string> {
  const params: Record<string, string> = {}
  if (filters.voivodeship) params.voivodeship = filters.voivodeship
  if (filters.city) params.city = filters.city
  if (filters.school_type && filters.school_type !== "all") params.school_type = filters.school_type
  params.ownership_public = String(filters.ownership_public)
  params.ownership_private = String(filters.ownership_private)
  // Always send this (even "" when no subtype is checked) so an
  // intentionally-empty subtype selection narrows results to none, rather
  // than being indistinguishable from "no subtype filter requested".
  if (filters.ownership_private) {
    params.ownership_subtype = filters.ownership_subtype.join(",")
  }
  params.ownership_include_unverified = String(filters.ownership_include_unverified)
  if (filters.students_min !== null) params.students_min = String(filters.students_min)
  if (filters.students_max !== null) params.students_max = String(filters.students_max)
  params.students_include_unknown = String(filters.students_include_unknown)
  if (filters.score_min !== null) params.score_min = String(filters.score_min)
  if (filters.score_max !== null) params.score_max = String(filters.score_max)
  params.score_include_unscored = String(filters.score_include_unscored)
  params.enrichment = filters.enrichment
  return params
}

/** Properly-typed filter payload for JSON request bodies (POST /pipeline/pull),
 * as opposed to filtersToParams' stringified version for URLSearchParams. */
export function filtersToApiBody(filters: LibraryFilters): Record<string, unknown> {
  const body: Record<string, unknown> = {
    ownership_public: filters.ownership_public,
    ownership_private: filters.ownership_private,
    ownership_include_unverified: filters.ownership_include_unverified,
    students_include_unknown: filters.students_include_unknown,
  }
  if (filters.voivodeship) body.voivodeship = filters.voivodeship
  if (filters.city) body.city = filters.city
  if (filters.school_type && filters.school_type !== "all") body.school_type = filters.school_type
  if (filters.ownership_private) {
    body.ownership_subtype = filters.ownership_subtype.join(",")
  }
  if (filters.students_min !== null) body.students_min = filters.students_min
  if (filters.students_max !== null) body.students_max = filters.students_max
  if (filters.score_min !== null) body.score_min = filters.score_min
  if (filters.score_max !== null) body.score_max = filters.score_max
  body.score_include_unscored = filters.score_include_unscored
  body.enrichment = filters.enrichment
  return body
}

function toQueryString(params: Record<string, string>): string {
  const qs = new URLSearchParams(params).toString()
  return qs ? `?${qs}` : ""
}

export async function listSchools(
  filters: LibraryFilters,
  page: number,
  pageSize: number,
  sort = "score:desc",
  resultLimit?: number | null
): Promise<SchoolListResponse> {
  const params: Record<string, string> = { ...filtersToParams(filters), page: String(page), page_size: String(pageSize), sort }
  if (resultLimit) params.result_limit = String(resultLimit)
  return api.get<SchoolListResponse>(`/schools${toQueryString(params)}`)
}

export async function countSchools(filters: LibraryFilters): Promise<number> {
  const { count } = await api.get<{ count: number }>(`/schools/count${toQueryString(filtersToParams(filters))}`)
  return count
}

/** Every school id matching the given filters, across every page -- lets
 * "select all N matching my filters" act on the whole filtered set rather
 * than just whatever's on the current page. */
export async function listSchoolIds(filters: LibraryFilters): Promise<number[]> {
  const { ids } = await api.get<{ ids: number[] }>(`/schools/ids${toQueryString(filtersToParams(filters))}`)
  return ids
}

export async function getSchool(id: number): Promise<School> {
  return api.get<School>(`/schools/${id}`)
}

export async function getSchoolContacts(id: number): Promise<SchoolContact[]> {
  return api.get<SchoolContact[]>(`/schools/${id}/contacts`)
}

export async function updateSchoolWebsite(id: number, websiteUrl: string): Promise<School> {
  return api.patch<School>(`/schools/${id}/website`, { website_url: websiteUrl })
}

export interface DirectoryQuery {
  q?: string
  status?: "all" | "available" | "pipeline" | "campaign"
  campaignId?: number | null
  sort?: string
  page?: number
  pageSize?: number
}

/** The full register with each school's assignment -- see the Directory tab. */
export async function listDirectory(args: DirectoryQuery = {}): Promise<DirectoryListResponse> {
  const params = new URLSearchParams()
  if (args.q) params.set("q", args.q)
  if (args.status && args.status !== "all") params.set("status", args.status)
  if (args.campaignId !== null && args.campaignId !== undefined) params.set("campaign_id", String(args.campaignId))
  if (args.sort) params.set("sort", args.sort)
  params.set("page", String(args.page ?? 1))
  params.set("page_size", String(args.pageSize ?? 50))
  return api.get<DirectoryListResponse>(`/schools/directory?${params.toString()}`)
}

export async function listVoivodeships(scope: FacetScope = "library"): Promise<VoivodeshipFacet[]> {
  return api.get<VoivodeshipFacet[]>(`/schools/facets/voivodeships?scope=${scope}`)
}

export async function listCities(voivodeship: string | null, scope: FacetScope = "library"): Promise<CityFacet[]> {
  const params = new URLSearchParams({ scope })
  if (voivodeship) params.set("voivodeship", voivodeship)
  return api.get<CityFacet[]>(`/schools/facets/cities?${params.toString()}`)
}
