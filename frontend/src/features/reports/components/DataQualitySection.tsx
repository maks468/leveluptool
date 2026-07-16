import { useQuery } from "@tanstack/react-query"
import { getDataQualityReport } from "@/api/reports"
import { queryKeys } from "@/api/queryKeys"
import { MeterRow } from "@/components/shared/MeterRow"

function pctOf(numerator: number, denominator: number): number {
  return denominator > 0 ? (numerator / denominator) * 100 : 0
}

function pctLabel(numerator: number, denominator: number): string {
  if (denominator === 0) return "—"
  const raw = pctOf(numerator, denominator)
  // At 25k-school scale a handful of hits rounds to a misleading "0%" --
  // show one decimal place only in that edge case, whole numbers otherwise.
  const shown = numerator > 0 && raw < 0.5 ? raw.toFixed(2) : Math.round(raw)
  return `${numerator} (${shown}%)`
}

export function DataQualitySection() {
  const { data, isLoading } = useQuery({ queryKey: queryKeys.dataQualityReport(), queryFn: getDataQualityReport })

  if (isLoading || !data) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <p className="text-sm text-[var(--color-text-muted)]">Loading&hellip;</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold">Library coverage</h2>
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">
          {data.library_total.toLocaleString()} active schools &mdash; where the auto-enrich dial has the most room to help.
        </p>
        <div className="space-y-2">
          <MeterRow
            label="Ever enriched"
            pct={pctOf(data.library_enriched_attempted, data.library_total)}
            valueLabel={pctLabel(data.library_enriched_attempted, data.library_total)}
          />
          <MeterRow
            label="Never attempted"
            pct={pctOf(data.library_never_attempted, data.library_total)}
            valueLabel={pctLabel(data.library_never_attempted, data.library_total)}
            colorClass="bg-slate-400 dark:bg-slate-500"
          />
          <MeterRow
            label="Verified contact found"
            pct={pctOf(data.library_verified_contact, data.library_total)}
            valueLabel={pctLabel(data.library_verified_contact, data.library_total)}
            colorClass="bg-green-500"
            title="Named person + their own email"
          />
          <MeterRow
            label="Partial contact found"
            pct={pctOf(data.library_partial_contact, data.library_total)}
            valueLabel={pctLabel(data.library_partial_contact, data.library_total)}
            colorClass="bg-amber-500"
            title="Named person found, but no personal email"
          />
        </div>
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold">Pipeline data quality</h2>
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">
          {data.pipeline_total.toLocaleString()} schools in the pipeline &mdash; gaps in the schools you're actively pursuing.
        </p>
        {data.pipeline_total === 0 ? (
          <p className="text-sm text-[var(--color-text-muted)]">Nothing in the pipeline yet.</p>
        ) : (
          <div className="space-y-2">
            <MeterRow
              label="Missing verified contact"
              pct={pctOf(data.pipeline_missing_verified_contact, data.pipeline_total)}
              valueLabel={pctLabel(data.pipeline_missing_verified_contact, data.pipeline_total)}
              colorClass="bg-amber-500"
              title="No named person + their own email found yet"
            />
            <MeterRow
              label="Partial contact only"
              pct={pctOf(data.pipeline_partial_contact, data.pipeline_total)}
              valueLabel={pctLabel(data.pipeline_partial_contact, data.pipeline_total)}
              colorClass="bg-amber-500"
              title="Named person found, but no personal email"
            />
            <MeterRow
              label="Never enriched"
              pct={pctOf(data.pipeline_never_enriched, data.pipeline_total)}
              valueLabel={pctLabel(data.pipeline_never_enriched, data.pipeline_total)}
              colorClass="bg-amber-500"
            />
            <MeterRow
              label="No follow-up set"
              pct={pctOf(data.pipeline_no_follow_up, data.pipeline_active_total)}
              valueLabel={pctLabel(data.pipeline_no_follow_up, data.pipeline_active_total)}
              colorClass="bg-amber-500"
              title="Of active (non-won/lost) pipeline schools"
            />
            <MeterRow
              label="No activity in 14+ days"
              pct={pctOf(data.pipeline_stale_14d, data.pipeline_active_total)}
              valueLabel={pctLabel(data.pipeline_stale_14d, data.pipeline_active_total)}
              colorClass="bg-red-500"
              title="Of active (non-won/lost) pipeline schools"
            />
          </div>
        )}
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 lg:col-span-2">
        <h2 className="mb-1 text-sm font-semibold">Enrichment job health</h2>
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">
          {data.enrichment_items_total.toLocaleString()} enrichment attempts completed to date.
        </p>
        {data.enrichment_items_total === 0 ? (
          <p className="text-sm text-[var(--color-text-muted)]">No enrichment jobs have run yet.</p>
        ) : (
          <MeterRow
            label="Success rate"
            pct={(data.enrichment_success_rate ?? 0) * 100}
            valueLabel={`${data.enrichment_items_success} of ${data.enrichment_items_total} (${Math.round((data.enrichment_success_rate ?? 0) * 100)}%)`}
            colorClass="bg-green-500"
          />
        )}
      </div>
    </div>
  )
}
