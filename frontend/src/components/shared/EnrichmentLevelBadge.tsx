import type { EnrichmentLevel } from "@/types/domain"
import { Badge, type BadgeColor } from "@/components/ui/Badge"

export const ENRICHMENT_LEVEL_CONFIG: Record<EnrichmentLevel, { label: string; color: BadgeColor }> = {
  successful: { label: "Successful", color: "green" },
  partial: { label: "Partial", color: "blue" },
  basic: { label: "Basic", color: "amber" },
  not_enriched: { label: "Not enriched", color: "slate" },
}

const LEVEL_TITLE: Record<EnrichmentLevel, string> = {
  successful: "A priority (personal) email was found for the director or English teacher",
  partial: "The English teacher's name is known, but no priority email yet",
  basic: "The director's name and an email (possibly a shared office one) are known",
  not_enriched: "No usable contact info found yet",
}

export function EnrichmentLevelBadge({ level }: { level: EnrichmentLevel }) {
  const { label, color } = ENRICHMENT_LEVEL_CONFIG[level]
  return (
    <Badge color={color} variant={level === "not_enriched" ? "dashed" : "solid"} title={LEVEL_TITLE[level]}>
      {label}
    </Badge>
  )
}
