import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { listQueue } from "@/api/pipeline"
import { queryKeys } from "@/api/queryKeys"
import { PIPELINE_STAGES, STAGE_LABELS, type PipelineStage, type QueueEntry } from "@/types/domain"
import { ScoreBadge } from "@/components/shared/ScoreBadge"
import { StagePill } from "@/components/shared/StagePill"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { useMoveStageMutation } from "@/features/pipeline/useMoveStageMutation"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"
import { shortenSchoolName } from "@/lib/schoolName"
import { cn } from "@/lib/utils"

const LIMIT_OPTIONS = [20, 50, 100]

type Tone = "red" | "amber" | "indigo" | "slate"

function reasonTone(reason: string): Tone {
  if (reason.startsWith("Follow-up overdue")) return "red"
  if (reason.startsWith("Follow-up due today")) return "amber"
  if (reason.startsWith("Not yet contacted")) return "indigo"
  return "slate"
}

const TONE_BORDER: Record<Tone, string> = {
  red: "border-l-red-500",
  amber: "border-l-amber-500",
  indigo: "border-l-indigo-500",
  slate: "border-l-slate-300 dark:border-l-slate-600",
}

const TONE_TEXT: Record<Tone, string> = {
  red: "text-red-700 dark:text-red-400",
  amber: "text-amber-700 dark:text-amber-400",
  indigo: "text-indigo-700 dark:text-indigo-400",
  slate: "text-[var(--color-text-muted)]",
}

function formatLastActivity(iso: string | null): string {
  if (!iso) return "No activity yet"
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return "Active today"
  if (days === 1) return "1 day ago"
  return `${days} days ago`
}

function QueueRow({ entry, rank, onOpen }: { entry: QueueEntry; rank: number; onOpen: (id: number) => void }) {
  const moveStage = useMoveStageMutation()
  const tone = reasonTone(entry.queue_reason)

  return (
    <div
      className={cn(
        "flex items-center gap-3 border-l-4 border-b border-[var(--color-border)] px-3 py-2.5 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-800/50",
        TONE_BORDER[tone]
      )}
    >
      <span className="w-6 flex-shrink-0 text-center text-xs font-semibold text-[var(--color-text-muted)]">{rank}</span>

      <button
        type="button"
        className="min-w-0 flex-1 text-left"
        onClick={() => onOpen(entry.id)}
        title={entry.name}
      >
        <div className="truncate text-sm font-medium hover:underline">{shortenSchoolName(entry.name, entry.city, entry.name_disambiguator)}</div>
        <div className={cn("mt-0.5 text-xs font-medium", TONE_TEXT[tone])}>{entry.queue_reason}</div>
      </button>

      <span className="hidden w-28 flex-shrink-0 text-xs text-[var(--color-text-muted)] sm:block">
        <DataValueCell value={entry.city} />
      </span>

      <span className="hidden w-28 flex-shrink-0 text-xs text-[var(--color-text-muted)] md:block">
        {formatLastActivity(entry.last_activity_at)}
      </span>

      <div className="flex-shrink-0">
        <ScoreBadge score={entry.score} />
      </div>

      <div className="flex-shrink-0">
        <StagePill stage={entry.stage} />
      </div>

      <select
        className="flex-shrink-0 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-xs"
        value={entry.stage}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => moveStage.mutate({ schoolId: entry.id, stage: e.target.value as PipelineStage })}
      >
        {PIPELINE_STAGES.map((s) => (
          <option key={s} value={s}>
            {STAGE_LABELS[s]}
          </option>
        ))}
      </select>
    </div>
  )
}

export function PriorityQueuePage() {
  const [limit, setLimit] = useState(50)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: entries = [], isLoading } = useQuery({
    queryKey: queryKeys.queue(limit),
    queryFn: () => listQueue(limit),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Priority queue</h1>
          <p className="text-sm text-[var(--color-text-muted)]">
            Who to contact next, ranked: overdue follow-ups first, then due today, then not-yet-contacted by score,
            then everything else by score and staleness.
          </p>
        </div>
        <div className="flex gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-1">
          {LIMIT_OPTIONS.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setLimit(opt)}
              className={cn(
                "rounded-md px-3 py-1 text-sm font-medium transition-colors",
                limit === opt
                  ? "bg-[var(--color-accent)] text-[var(--color-accent-fg)]"
                  : "text-[var(--color-text-muted)] hover:bg-slate-100 dark:hover:bg-slate-800"
              )}
            >
              Top {opt}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
        {isLoading && <div className="px-3 py-6 text-center text-sm text-[var(--color-text-muted)]">Loading&hellip;</div>}
        {!isLoading && entries.length === 0 && (
          <div className="px-3 py-6 text-center text-sm text-[var(--color-text-muted)]">
            Nothing active in the pipeline yet &mdash; pull some schools in from the Library to build your queue.
          </div>
        )}
        {entries.map((entry, i) => (
          <QueueRow key={entry.id} entry={entry} rank={i + 1} onOpen={setSelectedId} />
        ))}
      </div>

      {selectedId !== null && <SchoolDetailDrawer schoolId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
