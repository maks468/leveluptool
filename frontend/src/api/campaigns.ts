import { api, API_BASE_URL } from "./client"
import type { Campaign, CampaignDetail } from "@/types/domain"

export interface MoveToCampaignResult {
  moved: number
  not_in_pipeline: number
  already_in_campaign: number
}

export async function listCampaigns(): Promise<Campaign[]> {
  return api.get<Campaign[]>("/campaigns")
}

export async function createCampaign(name: string): Promise<Campaign> {
  return api.post<Campaign>("/campaigns", { name })
}

export async function getCampaign(id: number): Promise<CampaignDetail> {
  return api.get<CampaignDetail>(`/campaigns/${id}`)
}

/** Rename and/or edit the description -- send only the fields to change.
 * An empty-string description clears it. */
export async function updateCampaign(
  id: number,
  patch: { name?: string; description?: string }
): Promise<Campaign> {
  return api.patch<Campaign>(`/campaigns/${id}`, patch)
}

/** Plain navigation (not a fetch) so the browser handles the download --
 * same pattern as the Library/Pipeline CSV exports. */
export function exportCampaignCsvUrl(id: number): string {
  return `${API_BASE_URL}/campaigns/${id}/export`
}

/** Move semantics, not copy: the schools leave the pipeline in the same
 * transaction that adds them to the campaign. */
export async function moveSchoolsToCampaign(campaignId: number, schoolIds: number[]): Promise<MoveToCampaignResult> {
  return api.post<MoveToCampaignResult>(`/campaigns/${campaignId}/schools`, { school_ids: schoolIds })
}

/** The one way out of a campaign: back to the pipeline, at the stage the
 * school held when it was parked. */
export async function returnSchoolToPipeline(campaignId: number, schoolId: number): Promise<MoveToCampaignResult> {
  return api.post<MoveToCampaignResult>(`/campaigns/${campaignId}/schools/${schoolId}/return`, {})
}

/** Empties the whole campaign back into the pipeline -- every school at the
 * stage it held when it was parked. The empty container survives. */
export async function returnAllToPipeline(campaignId: number): Promise<MoveToCampaignResult> {
  return api.post<MoveToCampaignResult>(`/campaigns/${campaignId}/return-all`, {})
}

/** Deletes the container and its memberships -- the schools become plain
 * Library rows again (NOT pipeline rows). */
export async function deleteCampaign(campaignId: number): Promise<Campaign> {
  return api.delete<Campaign>(`/campaigns/${campaignId}`)
}
