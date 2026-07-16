import { useQuery } from "@tanstack/react-query"
import { getFunnelReport } from "@/api/reports"
import { queryKeys } from "@/api/queryKeys"
import { STAGE_LABELS } from "@/types/domain"
import { StatCard } from "@/features/dashboard/components/StatCard"
import { MeterRow } from "@/components/shared/MeterRow"

function pct(n: number | null): string {
  if (n === null) return "—"
  return `${Math.round(n * 100)}%`
}

export function FunnelSection() {
  const { data, isLoading } = useQuery({ queryKey: queryKeys.funnelReport(), queryFn: getFunnelReport })

  if (isLoading || !data) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <p className="text-sm text-[var(--color-text-muted)]">Loading&hellip;</p>
      </div>
    )
  }

  const pipelineTotal = data.stage_reached[0]?.reached ?? 0

  if (pipelineTotal === 0) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="text-sm font-semibold">Conversion funnel</h2>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          Nothing in the pipeline yet &mdash; pull some schools in to start building funnel data.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Win rate"
          value={pct(data.win_rate)}
          sublabel={
            data.win_rate === null
              ? "No won/lost deals yet"
              : `${data.stage_reached.at(-1)!.reached} won of ${data.stage_reached.at(-1)!.reached + data.lost_count} decided`
          }
        />
        <StatCard
          label="Response rate"
          value={pct(data.response_rate)}
          sublabel={
            data.response_rate === null
              ? "Nobody contacted yet"
              : `${data.stage_reached.find((s) => s.stage === "responded")!.reached} responded of ${data.stage_reached.find((s) => s.stage === "contacted")!.reached} contacted`
          }
        />
        <StatCard
          label="Avg score, won deals"
          value={data.avg_score_won !== null ? Math.round(data.avg_score_won) : "—"}
          sublabel={data.avg_score_won === null ? "No won deals yet" : "out of 100"}
        />
        <StatCard
          label="Avg score, lost deals"
          value={data.avg_score_lost !== null ? Math.round(data.avg_score_lost) : "—"}
          sublabel={data.avg_score_lost === null ? "No lost deals yet" : "out of 100"}
        />
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-3 text-sm font-semibold">Funnel &mdash; how far pipeline schools get</h2>
        <div className="space-y-2">
          {data.stage_reached.map((s, i) => {
            const prev = i > 0 ? data.stage_reached[i - 1].reached : null
            const stepRate = prev && prev > 0 ? s.reached / prev : null
            return (
              <MeterRow
                key={s.stage}
                label={STAGE_LABELS[s.stage]}
                pct={pipelineTotal > 0 ? (s.reached / pipelineTotal) * 100 : 0}
                valueLabel={`${s.reached}${stepRate !== null ? ` (${Math.round(stepRate * 100)}% of prev)` : ""}`}
                title={`${s.reached} of ${pipelineTotal} schools ever reached this stage`}
              />
            )
          })}
          <MeterRow
            label="Lost"
            pct={pipelineTotal > 0 ? (data.lost_count / pipelineTotal) * 100 : 0}
            valueLabel={`${data.lost_count}`}
            colorClass="bg-red-500"
            title="Schools currently or previously marked Lost"
          />
        </div>
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold">Win rate by score band</h2>
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">
          Only counts schools with a decided outcome (won or lost) &mdash; does a higher score actually predict a won deal?
        </p>
        <div className="space-y-2">
          {data.score_bands.map((band) => (
            <MeterRow
              key={band.band}
              label={`Score ${band.band}`}
              pct={band.win_rate !== null ? band.win_rate * 100 : 0}
              valueLabel={band.total > 0 ? `${pct(band.win_rate)} (${band.total} decided)` : "No decided deals"}
              colorClass="bg-green-500"
            />
          ))}
        </div>
      </div>
    </div>
  )
}
