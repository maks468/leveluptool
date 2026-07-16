import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Loader2, X, ChevronUp, ChevronDown } from "lucide-react"
import { useRecentEnrichmentJobs } from "./useEnrichmentJobs"
import { shortenSchoolName } from "@/lib/schoolName"
import { cn } from "@/lib/utils"

const RECENT_WINDOW_MS = 60 * 60 * 1000 // keep a finished job visible for up to an hour unless dismissed sooner

export function BatchJobTray() {
  const { data: allJobs = [] } = useRecentEnrichmentJobs()
  const [expanded, setExpanded] = useState(false)
  const [dismissedIds, setDismissedIds] = useState<Set<number>>(new Set())
  const navigate = useNavigate()

  const cutoff = Date.now() - RECENT_WINDOW_MS
  const jobs = allJobs.filter(
    (j) =>
      !dismissedIds.has(j.id) &&
      (j.status === "pending" || j.status === "running" || new Date(j.requested_at).getTime() > cutoff)
  )

  if (jobs.length === 0) return null

  const totalItems = jobs.flatMap((j) => j.items)
  const done = totalItems.filter((i) => i.status === "success" || i.status === "failed").length
  const failed = totalItems.filter((i) => i.status === "failed").length
  const allDone = jobs.every((j) => j.status === "done")

  return (
    <div className="fixed bottom-4 left-4 z-50 w-80 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] shadow-lg">
      <button
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
        onClick={() => setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          {!allDone && <Loader2 className="h-4 w-4 animate-spin text-[var(--color-accent)]" />}
          {allDone ? (
            <span>
              Enriched {done - failed} of {totalItems.length}
              {failed > 0 && ` — ${failed} failed`}
            </span>
          ) : (
            <span>
              Enriching schools&hellip; {done}/{totalItems.length} done
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          {allDone && (
            <X
              className="h-4 w-4 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
              onClick={(e) => {
                e.stopPropagation()
                setDismissedIds((prev) => new Set([...prev, ...jobs.map((j) => j.id)]))
              }}
            />
          )}
        </div>
      </button>
      <div className="h-1 w-full bg-slate-200 dark:bg-slate-700">
        <div
          className={cn("h-1 bg-[var(--color-accent)] transition-all", allDone && failed === 0 && "bg-green-500")}
          style={{ width: `${totalItems.length ? (done / totalItems.length) * 100 : 0}%` }}
        />
      </div>
      {expanded && (
        <div className="max-h-64 overflow-y-auto border-t border-[var(--color-border)] p-2 text-xs">
          {jobs.map((job) => (
            <div key={job.id} className="mb-2">
              <div className="mb-1 font-medium text-[var(--color-text-muted)]">Job #{job.id}</div>
              {job.items.map((item) => (
                <div key={item.school_id} className="flex items-center justify-between gap-2 py-0.5">
                  <button
                    type="button"
                    title={item.school_name}
                    className="min-w-0 flex-1 truncate text-left hover:underline"
                    onClick={() => navigate(`/schools/${item.school_id}`)}
                  >
                    {shortenSchoolName(item.school_name, item.school_city)}
                  </button>
                  <span
                    className={cn(
                      "flex-shrink-0",
                      item.status === "success" && "text-green-600",
                      item.status === "failed" && "text-red-600",
                      (item.status === "pending" || item.status === "running") && "text-[var(--color-text-muted)]"
                    )}
                  >
                    {item.status}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
