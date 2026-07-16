import { api } from "./client"
import type { DashboardSummary, RecentActivityEntry, School } from "@/types/domain"

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return api.get<DashboardSummary>("/dashboard/summary")
}

export async function getRecentActivity(limit = 10): Promise<RecentActivityEntry[]> {
  return api.get<RecentActivityEntry[]>(`/dashboard/recent-activity?limit=${limit}`)
}

export async function getTopLeads(limit = 10): Promise<School[]> {
  return api.get<School[]>(`/dashboard/top-leads?limit=${limit}`)
}
