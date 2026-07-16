import { api } from "./client"
import type { DataQualityReport, FunnelReport } from "@/types/domain"

export async function getFunnelReport(): Promise<FunnelReport> {
  return api.get<FunnelReport>("/reports/funnel")
}

export async function getDataQualityReport(): Promise<DataQualityReport> {
  return api.get<DataQualityReport>("/reports/data-quality")
}
