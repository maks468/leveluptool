import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { updateSchoolWebsite } from "@/api/schools"
import { startEnrichmentJob } from "@/api/enrichment"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { DataValueCell } from "@/components/shared/DataValueCell"
import type { School } from "@/types/domain"

/** Manual override for when the scraper can't find or reach a school's own
 * site. Saved as EvidenceSource.MANUAL server-side so it survives future
 * RSPO re-imports (unlike the raw RSPO field, which a blank/stale value
 * would otherwise silently reset), and immediately re-triggers enrichment
 * against the corrected URL. */
export function WebsiteField({ school }: { school: School }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(school.website_url ?? "")

  const save = useMutation({
    mutationFn: (url: string) => updateSchoolWebsite(school.id, url),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.school(school.id) })
      setEditing(false)
      await startEnrichmentJob([school.id])
      queryClient.invalidateQueries({ queryKey: queryKeys.enrichmentJobs() })
    },
  })

  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <DataValueCell value={school.website_url} />
        {school.website_url_source === "manual" && <Badge color="purple">Manual</Badge>}
        <button
          type="button"
          className="text-xs text-[var(--color-text-muted)] underline hover:text-[var(--color-text)]"
          onClick={() => {
            setValue(school.website_url ?? "")
            setEditing(true)
          }}
        >
          {school.website_url ? "Edit" : "Add"}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        type="text"
        autoFocus
        placeholder="https://szkola.example.pl"
        className="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setEditing(false)
        }}
      />
      <Button size="sm" onClick={() => save.mutate(value)} disabled={save.isPending || !value.trim()}>
        Save &amp; re-enrich
      </Button>
      <button
        type="button"
        className="text-xs text-[var(--color-text-muted)] underline"
        onClick={() => setEditing(false)}
      >
        Cancel
      </button>
      {save.isError && <p className="w-full text-xs text-red-500">Couldn't save that URL. Try again.</p>}
    </div>
  )
}
