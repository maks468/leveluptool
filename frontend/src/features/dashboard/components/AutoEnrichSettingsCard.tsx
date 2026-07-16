import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Zap } from "lucide-react"
import { getAutoEnrichSettings, updateAutoEnrichSettings } from "@/api/admin"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"

function formatRelative(iso: string | null): string {
  if (!iso) return "Never run yet"
  const ms = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(ms / 60_000)
  if (mins < 1) return "Just now"
  if (mins < 60) return `${mins} min ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/** Lets the whole library keep getting enriched ("N schools every M
 * minutes") without manually selecting batches -- picks the
 * highest-scored schools that have never been through an enrichment
 * attempt yet, so it converges on full coverage instead of retrying
 * dead ends. */
export function AutoEnrichSettingsCard() {
  const queryClient = useQueryClient()
  const { data: settings } = useQuery({
    queryKey: queryKeys.autoEnrichSettings(),
    queryFn: getAutoEnrichSettings,
    refetchInterval: 30_000,
  })

  const [enabled, setEnabled] = useState(false)
  const [schoolsPerRun, setSchoolsPerRun] = useState(20)
  const [intervalMinutes, setIntervalMinutes] = useState(60)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (settings && !dirty) {
      setEnabled(settings.enabled)
      setSchoolsPerRun(settings.schools_per_run)
      setIntervalMinutes(settings.interval_minutes)
    }
  }, [settings, dirty])

  const saveMutation = useMutation({
    mutationFn: () =>
      updateAutoEnrichSettings({
        enabled,
        schools_per_run: schoolsPerRun,
        interval_minutes: intervalMinutes,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.autoEnrichSettings(), data)
      setDirty(false)
    },
  })

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-start gap-3">
        <Zap className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--color-text-muted)]" />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold">Auto-enrich</h2>
            {settings?.enabled && <Badge color="green">Running</Badge>}
          </div>
          <p className="mt-1 text-xs text-[var(--color-text-muted)]">
            Keeps enriching the highest-scored, never-attempted schools in the background so the whole library
            reaches full coverage without manually selecting batches.
          </p>

          <div className="mt-3 flex flex-wrap items-end gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => {
                  setEnabled(e.target.checked)
                  setDirty(true)
                }}
              />
              Enabled
            </label>

            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Schools per run</label>
              <input
                type="number"
                min={1}
                className="w-24 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm"
                value={schoolsPerRun}
                onChange={(e) => {
                  setSchoolsPerRun(Number(e.target.value))
                  setDirty(true)
                }}
              />
            </div>

            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Every (minutes)</label>
              <input
                type="number"
                min={1}
                className="w-24 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm"
                value={intervalMinutes}
                onChange={(e) => {
                  setIntervalMinutes(Number(e.target.value))
                  setDirty(true)
                }}
              />
            </div>

            <Button
              size="sm"
              variant="primary"
              disabled={!dirty || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? "Saving…" : "Save"}
            </Button>
          </div>

          {settings && (
            <p className="mt-2 text-xs text-[var(--color-text-muted)]">
              Last run: {formatRelative(settings.last_run_at)}
              {settings.last_run_found_count !== null &&
                ` — enqueued ${settings.last_run_found_count} school${settings.last_run_found_count === 1 ? "" : "s"}`}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
