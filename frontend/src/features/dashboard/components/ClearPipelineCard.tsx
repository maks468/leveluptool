import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Eraser } from "lucide-react"
import { clearPipelineOnly } from "@/api/admin"
import { Button } from "@/components/ui/Button"
import { ConfirmDialog } from "@/components/ui/Dialog"

const CONFIRM_WORD = "confirm"

/** Empties the pipeline (memberships, stages, follow-ups) and the outreach
 * half of the activity log, while keeping every enriched contact, the
 * enrichment history, tags, and saved views. The narrow alternative to the
 * full Reset tool below it -- rebuilding the pipeline shouldn't cost the
 * contacts that took real crawling and LLM calls to find. */
export function ClearPipelineCard() {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState("")
  const [result, setResult] = useState<Awaited<ReturnType<typeof clearPipelineOnly>> | null>(null)
  const queryClient = useQueryClient()

  const clearMutation = useMutation({
    mutationFn: () => clearPipelineOnly(input),
    onSuccess: (data) => {
      setResult(data)
      setInput("")
      setOpen(false)
      queryClient.invalidateQueries()
    },
  })

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setInput("")
      clearMutation.reset()
    }
  }

  const canConfirm = input.trim().toLowerCase() === CONFIRM_WORD

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4 dark:border-amber-900/50 dark:bg-amber-950/20">
      <div className="flex items-start gap-3">
        <Eraser className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600 dark:text-amber-400" />
        <div className="flex-1">
          <h2 className="text-sm font-semibold text-amber-900 dark:text-amber-300">Clear pipeline</h2>
          <p className="mt-1 text-xs text-amber-800/80 dark:text-amber-300/70">
            Empties the pipeline (stages, follow-ups) and its outreach history, so you can rebuild it from scratch.
            Keeps everything enrichment found: contacts, director/teacher names, enrichment history &mdash; plus tags
            and saved views.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
          Clear pipeline&hellip;
        </Button>
      </div>

      <ConfirmDialog open={open} onOpenChange={handleOpenChange} title="Clear the pipeline?">
        <div className="space-y-4">
          <p className="text-sm text-[var(--color-text-muted)]">This permanently deletes:</p>
          <ul className="list-inside list-disc space-y-0.5 text-sm text-[var(--color-text-muted)]">
            <li>Every school&rsquo;s pipeline membership, stage, and follow-up</li>
            <li>Outreach activity: pulled-into-pipeline, stage changes, and notes</li>
          </ul>
          <p className="text-sm text-[var(--color-text-muted)]">
            Enriched contacts, director/teacher names, enrichment history, tags, saved views, scores, and the Library
            are <strong>not</strong> touched. This cannot be undone.
          </p>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">
              Type <span className="font-mono font-semibold text-[var(--color-text)]">{CONFIRM_WORD}</span> to
              proceed
            </label>
            <input
              type="text"
              autoFocus
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canConfirm && !clearMutation.isPending) clearMutation.mutate()
              }}
            />
          </div>

          {clearMutation.isError && (
            <p className="text-sm text-red-600">Something went wrong &mdash; nothing was changed. Try again.</p>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={!canConfirm || clearMutation.isPending}
              onClick={() => clearMutation.mutate()}
            >
              {clearMutation.isPending ? "Clearing…" : "Clear pipeline"}
            </Button>
          </div>
        </div>
      </ConfirmDialog>

      {result && (
        <div className="mt-3 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-[var(--color-text-muted)]">
          Pipeline cleared: {result.pipeline_schools_removed} schools and {result.activity_log_removed} outreach
          entries removed. Kept {result.school_contacts_kept} enriched contacts and {result.activity_log_kept}{" "}
          enrichment/record entries.
        </div>
      )}
    </div>
  )
}
