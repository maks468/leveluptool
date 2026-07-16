import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckSquare, Sparkles, Tag as TagIcon, X } from "lucide-react"
import { bulkSetStage } from "@/api/pipeline"
import { bulkAddTag, createTag, listTags } from "@/api/crm"
import { startEnrichmentJob } from "@/api/enrichment"
import { queryKeys } from "@/api/queryKeys"
import { PIPELINE_STAGES, STAGE_LABELS, type PipelineStage } from "@/types/domain"
import { Button } from "@/components/ui/Button"

const LARGE_BATCH_CONFIRM_THRESHOLD = 25

function invalidateAfterBulkChange(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["pipeline"] })
  queryClient.invalidateQueries({ queryKey: ["pipeline-queue"] })
  queryClient.invalidateQueries({ queryKey: ["pipeline-map"] })
  queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] })
  queryClient.invalidateQueries({ queryKey: ["dashboard-activity"] })
}

/** Selection is passed in, not read from a global store -- once the
 * Pipeline page can show several panels side by side, each panel needs
 * its own independent selection, not one shared across all of them. */
export function PipelineBulkActionBar({
  selectedIds,
  clear,
}: {
  selectedIds: Set<number>
  clear: () => void
}) {
  const [stageChoice, setStageChoice] = useState<PipelineStage>("contacted")
  const [tagChoice, setTagChoice] = useState<string>("")
  const [newTagName, setNewTagName] = useState("")
  const [addingTag, setAddingTag] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: tags = [] } = useQuery({ queryKey: queryKeys.tags(), queryFn: listTags })

  const stageMutation = useMutation({
    mutationFn: () => bulkSetStage(Array.from(selectedIds), stageChoice),
    onSuccess: (res) => {
      setResult(`Moved ${res.updated} school${res.updated === 1 ? "" : "s"} to "${STAGE_LABELS[stageChoice]}"`)
      clear()
      invalidateAfterBulkChange(queryClient)
    },
  })

  const tagMutation = useMutation({
    mutationFn: (tag: { id: number; name: string }) => bulkAddTag(tag.id, Array.from(selectedIds)),
    onSuccess: (res, tag) => {
      setResult(`Tagged ${res.updated} school${res.updated === 1 ? "" : "s"} with "${tag.name}"`)
      clear()
      setTagChoice("")
      queryClient.invalidateQueries({ queryKey: queryKeys.tags() })
      queryClient.invalidateQueries({ queryKey: ["school-tags"] })
    },
  })

  const createAndTagMutation = useMutation({
    mutationFn: (name: string) => createTag(name, "slate"),
    onSuccess: (tag) => {
      setNewTagName("")
      setAddingTag(false)
      tagMutation.mutate({ id: tag.id, name: tag.name })
    },
  })

  const enrichMutation = useMutation({
    mutationFn: () => startEnrichmentJob(Array.from(selectedIds)),
    onSuccess: () => {
      setResult(`Enrichment started for ${selectedIds.size} school${selectedIds.size === 1 ? "" : "s"} — see the tray in the corner.`)
      clear()
      queryClient.invalidateQueries({ queryKey: queryKeys.enrichmentJobs() })
    },
  })

  function handleEnrichSelected() {
    if (
      selectedIds.size > LARGE_BATCH_CONFIRM_THRESHOLD &&
      !window.confirm(
        `Enrich ${selectedIds.size} schools? Each one crawls its website and, if needed, runs a web search -- this can take a while and may hit search rate limits for very large batches.`
      )
    ) {
      return
    }
    enrichMutation.mutate()
  }

  if (selectedIds.size === 0) {
    if (!result) return null
    return (
      <div className="flex items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
        <span className="text-sm text-green-600">{result}</span>
        <button type="button" className="text-xs text-[var(--color-text-muted)] hover:underline" onClick={() => setResult(null)}>
          Dismiss
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-accent)] bg-[var(--color-surface)] p-3">
      <span className="flex items-center gap-1.5 text-sm font-medium">
        <CheckSquare className="h-4 w-4" />
        {selectedIds.size} selected
      </span>

      <span className="h-6 w-px bg-[var(--color-border)]" />

      <div className="flex items-center gap-2">
        <select
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
          value={stageChoice}
          onChange={(e) => setStageChoice(e.target.value as PipelineStage)}
        >
          {PIPELINE_STAGES.map((s) => (
            <option key={s} value={s}>
              {STAGE_LABELS[s]}
            </option>
          ))}
        </select>
        <Button size="sm" disabled={stageMutation.isPending} onClick={() => stageMutation.mutate()}>
          Move to stage
        </Button>
      </div>

      <span className="h-6 w-px bg-[var(--color-border)]" />

      {!addingTag ? (
        <div className="flex items-center gap-2">
          <select
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={tagChoice}
            onChange={(e) => setTagChoice(e.target.value)}
          >
            <option value="">Choose tag&hellip;</option>
            {tags.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={tagChoice === "" || tagMutation.isPending}
            onClick={() => {
              const tag = tags.find((t) => t.id === Number(tagChoice))
              if (tag) tagMutation.mutate(tag)
            }}
          >
            <TagIcon className="h-3.5 w-3.5" />
            Add tag
          </Button>
          <button
            type="button"
            className="text-xs text-[var(--color-accent)] hover:underline"
            onClick={() => setAddingTag(true)}
          >
            + New tag
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <input
            type="text"
            autoFocus
            placeholder="New tag name"
            className="w-32 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newTagName.trim()) createAndTagMutation.mutate(newTagName.trim())
              if (e.key === "Escape") setAddingTag(false)
            }}
          />
          <Button
            size="sm"
            disabled={!newTagName.trim() || createAndTagMutation.isPending}
            onClick={() => createAndTagMutation.mutate(newTagName.trim())}
          >
            Create &amp; tag
          </Button>
          <button type="button" className="text-xs text-[var(--color-text-muted)] hover:underline" onClick={() => setAddingTag(false)}>
            Cancel
          </button>
        </div>
      )}

      <span className="h-6 w-px bg-[var(--color-border)]" />

      <Button size="sm" disabled={enrichMutation.isPending} onClick={handleEnrichSelected}>
        <Sparkles className="h-3.5 w-3.5" />
        Enrich selected
      </Button>

      <span className="h-6 w-px bg-[var(--color-border)]" />

      <Button variant="ghost" size="sm" onClick={clear}>
        <X className="h-3.5 w-3.5" />
        Clear selection
      </Button>

      {result && <span className="text-sm text-green-600">{result}</span>}
    </div>
  )
}
