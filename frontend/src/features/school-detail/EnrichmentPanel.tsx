import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Sparkles } from "lucide-react"
import { startEnrichmentJob } from "@/api/enrichment"
import { getActivity } from "@/api/pipeline"
import { getSchoolContacts } from "@/api/schools"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import type { ContactQuality, School } from "@/types/domain"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { EnrichmentLevelBadge } from "@/components/shared/EnrichmentLevelBadge"
import { EnrichmentSourcesDisclosure } from "./EnrichmentSourcesDisclosure"
import { WebsiteField } from "./WebsiteField"

const CONTACT_TYPE_LABEL: Record<string, string> = {
  director: "Director",
  english_coordinator: "English teacher",
  general: "General (school office)",
}

const CONTACT_QUALITY_BADGE: Record<ContactQuality, { color: "green" | "amber" | "red"; label: string }> = {
  verified: { color: "green", label: "Verified" },
  partial: { color: "amber", label: "Partial" },
  failed: { color: "red", label: "Failed" },
}

export function EnrichmentPanel({ school }: { school: School }) {
  const queryClient = useQueryClient()

  const { data: contacts = [] } = useQuery({
    queryKey: queryKeys.schoolContacts(school.id),
    queryFn: () => getSchoolContacts(school.id),
  })

  const { data: activity = [] } = useQuery({
    queryKey: queryKeys.activity(school.id),
    queryFn: () => getActivity(school.id),
  })
  const lastEnrichment = activity.find((e) => e.activity_type === "enrichment_completed")

  const enrich = useMutation({
    mutationFn: () => startEnrichmentJob([school.id]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.enrichmentJobs() })
    },
  })

  return (
    <div className="rounded-md border border-[var(--color-border)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">Contact details</h3>
          <EnrichmentLevelBadge level={school.enrichment_level} />
        </div>
        <Button size="sm" onClick={() => enrich.mutate()} disabled={enrich.isPending}>
          <Sparkles className="h-3.5 w-3.5" />
          Enrich
        </Button>
      </div>

      {!school.website_url && (
        <p className="mb-2 text-xs text-[var(--color-text-muted)]">
          No website on file &mdash; enrichment falls back to a web search instead.
        </p>
      )}

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-[var(--color-text-muted)]">Director</dt>
        <dd>
          <DataValueCell value={school.director_name} />
        </dd>
        <dt className="text-[var(--color-text-muted)]">English teacher</dt>
        <dd>
          <DataValueCell value={school.english_teacher_name} />
        </dd>
        <dt className="text-[var(--color-text-muted)]">Website</dt>
        <dd>
          <WebsiteField school={school} />
        </dd>
        <dt className="text-[var(--color-text-muted)]">Speciality</dt>
        <dd>
          {school.specialty ? (
            <span className="inline-flex flex-wrap gap-1">
              {school.specialty.split(";").map((s) => (
                <Badge key={s} color="purple">
                  {s.trim()}
                </Badge>
              ))}
            </span>
          ) : (
            <DataValueCell value={null} />
          )}
        </dd>
      </dl>

      {contacts.length > 0 && (
        <div className="mt-3 space-y-2 border-t border-[var(--color-border)] pt-2">
          {contacts.map((c) => (
            <div key={c.id} className="text-xs">
              <div className="flex items-center gap-1.5 font-medium">
                {CONTACT_TYPE_LABEL[c.contact_type] ?? c.contact_type}
                {c.contact_type !== "general" && (
                  <Badge color={CONTACT_QUALITY_BADGE[c.contact_quality].color}>
                    {CONTACT_QUALITY_BADGE[c.contact_quality].label}
                  </Badge>
                )}
              </div>
              <div className="text-[var(--color-text-muted)]">
                {[c.person_name, c.email, c.phone].filter(Boolean).join(" · ") || "No contact info found"}
              </div>
            </div>
          ))}
        </div>
      )}

      {lastEnrichment && (
        <div className="mt-2 border-t border-[var(--color-border)] pt-2">
          <EnrichmentSourcesDisclosure metadata={lastEnrichment.metadata_json} />
        </div>
      )}

      {enrich.isSuccess && (
        <p className="mt-2 text-xs text-[var(--color-text-muted)]">
          Enrichment job started &mdash; check the tray in the corner for progress.
        </p>
      )}
    </div>
  )
}
