import { api, API_BASE_URL } from "./client"
import type { LibraryFilters, SavedView, SavedViewScope, SchoolSearchResult, Tag } from "@/types/domain"
import { filtersToParams } from "./schools"

export async function listSavedViews(scope: SavedViewScope = "library"): Promise<SavedView[]> {
  return api.get<SavedView[]>(`/saved-views?scope=${scope}`)
}

export async function createSavedView(args: {
  name: string
  scope?: SavedViewScope
  filters_json: object
  sort: string | null
  result_limit: number | null
}): Promise<SavedView> {
  return api.post<SavedView>("/saved-views", args)
}

export async function deleteSavedView(id: number): Promise<void> {
  return api.delete(`/saved-views/${id}`)
}

export async function toggleSavedViewFavorite(id: number): Promise<SavedView> {
  return api.patch<SavedView>(`/saved-views/${id}/favorite`)
}

export async function listTags(): Promise<Tag[]> {
  return api.get<Tag[]>("/tags")
}

export async function createTag(name: string, color: string): Promise<Tag> {
  return api.post<Tag>("/tags", { name, color })
}

export async function deleteTag(id: number): Promise<void> {
  return api.delete(`/tags/${id}`)
}

export async function getSchoolTags(schoolId: number): Promise<Tag[]> {
  return api.get<Tag[]>(`/schools/${schoolId}/tags`)
}

export async function addSchoolTag(schoolId: number, tagId: number): Promise<void> {
  return api.put(`/schools/${schoolId}/tags/${tagId}`)
}

export async function removeSchoolTag(schoolId: number, tagId: number): Promise<void> {
  return api.delete(`/schools/${schoolId}/tags/${tagId}`)
}

export async function bulkAddTag(tagId: number, schoolIds: number[]): Promise<{ updated: number }> {
  return api.put(`/tags/${tagId}/bulk`, { school_ids: schoolIds })
}

export async function searchSchools(q: string): Promise<SchoolSearchResult[]> {
  if (q.trim().length < 2) return []
  return api.get<SchoolSearchResult[]>(`/search?q=${encodeURIComponent(q)}`)
}

/** CSV export is a plain navigation (not a fetch call) so the browser
 * handles the Content-Disposition download itself. */
export function exportSchoolsCsvUrl(filters: LibraryFilters, sort: string): string {
  const params = new URLSearchParams({ ...filtersToParams(filters), sort })
  return `${API_BASE_URL}/schools/export?${params.toString()}`
}
