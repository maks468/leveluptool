import { PIPELINE_STAGES, STAGE_LABELS, type DashboardSummary } from "@/types/domain"
import { Link } from "react-router-dom"

export function StageBreakdown({ stageCounts }: { stageCounts: DashboardSummary["stage_counts"] }) {
  const total = PIPELINE_STAGES.reduce((sum, stage) => sum + (stageCounts[stage] ?? 0), 0)

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Pipeline by stage</h2>
        <Link to="/pipeline" className="text-xs text-[var(--color-accent)] hover:underline">
          Open pipeline &rarr;
        </Link>
      </div>
      {total === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">Nothing in the pipeline yet.</p>
      ) : (
        <div className="space-y-2">
          {PIPELINE_STAGES.map((stage) => {
            const count = stageCounts[stage] ?? 0
            const pct = total > 0 ? (count / total) * 100 : 0
            return (
              <div key={stage} className="flex items-center gap-2 text-xs">
                <span className="w-32 flex-shrink-0 text-[var(--color-text-muted)]">{STAGE_LABELS[stage]}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div className="h-full rounded-full bg-[var(--color-accent)]" style={{ width: `${pct}%` }} />
                </div>
                <span className="w-8 flex-shrink-0 text-right font-medium">{count}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
