import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"
import { resetPipelineWorkflow } from "@/api/admin"
import { Button } from "@/components/ui/Button"
import { ConfirmDialog } from "@/components/ui/Dialog"

const CONFIRM_WORD = "confirm"

/** Wipes pipeline/CRM workflow state (stages, activity, enrichment jobs
 * and the contacts they found, tags, saved views, follow-ups) back to a
 * freshly-imported state. Never touches the school Library, scores, or
 * Perspektywy rankings -- those take a real import/scoring run to
 * reproduce, and aren't "workflow" to reset. */
export function ResetToolCard() {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState("")
  const [result, setResult] = useState<Awaited<ReturnType<typeof resetPipelineWorkflow>> | null>(null)
  const queryClient = useQueryClient()

  const resetMutation = useMutation({
    mutationFn: () => resetPipelineWorkflow(input),
    onSuccess: (data) => {
      setResult(data)
      setInput("")
      queryClient.invalidateQueries()
    },
  })

  function handleOpenChange(next: boolean) {
    setOpen(next)
    if (!next) {
      setInput("")
      resetMutation.reset()
    }
  }

  const canConfirm = input.trim().toLowerCase() === CONFIRM_WORD

  return (
    <div className="rounded-lg border border-red-200 bg-red-50/50 p-4 dark:border-red-900/50 dark:bg-red-950/20">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-600 dark:text-red-400" />
        <div className="flex-1">
          <h2 className="text-sm font-semibold text-red-900 dark:text-red-300">Reset tool</h2>
          <p className="mt-1 text-xs text-red-800/80 dark:text-red-300/70">
            Permanently clears pipeline stages, campaigns, activity history, enrichment jobs and the contacts they
            found, tags, saved views, and follow-ups. The school Library, scores, and rankings are kept.
          </p>
        </div>
        <Button variant="danger" size="sm" onClick={() => setOpen(true)}>
          Reset tool&hellip;
        </Button>
      </div>

      <ConfirmDialog open={open} onOpenChange={handleOpenChange} title="Reset the pipeline & CRM workflow?">
        <div className="space-y-4">
          <p className="text-sm text-[var(--color-text-muted)]">This permanently deletes, for every school:</p>
          <ul className="list-inside list-disc space-y-0.5 text-sm text-[var(--color-text-muted)]">
            <li>Pipeline stage and follow-up dates</li>
            <li>Campaigns and their school lists</li>
            <li>Activity log entries</li>
            <li>Enrichment jobs and the director/English-teacher/email contacts they found</li>
            <li>Tags and saved views</li>
          </ul>
          <p className="text-sm text-[var(--color-text-muted)]">
            The school Library, scores, and Perspektywy rankings are <strong>not</strong> touched. This cannot be
            undone.
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
                if (e.key === "Enter" && canConfirm && !resetMutation.isPending) resetMutation.mutate()
              }}
            />
          </div>

          {resetMutation.isError && (
            <p className="text-sm text-red-600">Something went wrong &mdash; nothing was changed. Try again.</p>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => handleOpenChange(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={!canConfirm || resetMutation.isPending}
              onClick={() => resetMutation.mutate()}
            >
              {resetMutation.isPending ? "Resetting…" : "Reset everything"}
            </Button>
          </div>
        </div>
      </ConfirmDialog>

      {result && (
        <div className="mt-3 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-xs text-[var(--color-text-muted)]">
          Reset complete: {result.pipeline_schools_removed} pipeline schools, {result.campaigns_removed} campaigns (
          {result.campaign_schools_removed} schools), {result.activity_log_removed} activity entries,{" "}
          {result.enrichment_jobs_removed} enrichment jobs, {result.school_contacts_removed} contacts,{" "}
          {result.tags_removed} tags, and {result.saved_views_removed} saved views removed.
        </div>
      )}
    </div>
  )
}
