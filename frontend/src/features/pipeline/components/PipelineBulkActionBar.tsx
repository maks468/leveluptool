import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Archive, BookMarked, CheckSquare, Sparkles, Tag as TagIcon, X } from "lucide-react"
import { bulkSetStage, removeFromPipeline } from "@/api/pipeline"
import { bulkAddTag, createTag, listTags } from "@/api/crm"
import { createCampaign, listCampaigns, moveSchoolsToCampaign } from "@/api/campaigns"
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
  const [campaignChoice, setCampaignChoice] = useState<string>("")
  const [newCampaignName, setNewCampaignName] = useState("")
  const [addingCampaign, setAddingCampaign] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: tags = [] } = useQuery({ queryKey: queryKeys.tags(), queryFn: listTags })
  const { data: campaigns = [] } = useQuery({ queryKey: queryKeys.campaigns(), queryFn: listCampaigns })

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

  // Move semantics: the schools LEAVE the pipeline into the campaign
  // container in one transaction -- which is the point (a campaigned school
  // can't be double-contacted from the pipeline).
  const campaignMutation = useMutation({
    mutationFn: (campaign: { id: number; name: string }) =>
      moveSchoolsToCampaign(campaign.id, Array.from(selectedIds)),
    onSuccess: (res, campaign) => {
      const skipped = res.not_in_pipeline + res.already_in_campaign
      setResult(
        `Moved ${res.moved} school${res.moved === 1 ? "" : "s"} to campaign "${campaign.name}"` +
          (skipped > 0 ? ` (${skipped} skipped)` : "")
      )
      clear()
      setCampaignChoice("")
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns() })
      queryClient.invalidateQueries({ queryKey: ["campaign"] })
      queryClient.invalidateQueries({ queryKey: ["schools"] })
      invalidateAfterBulkChange(queryClient)
    },
  })

  const createAndMoveMutation = useMutation({
    mutationFn: (name: string) => createCampaign(name),
    onSuccess: (campaign) => {
      setNewCampaignName("")
      setAddingCampaign(false)
      campaignMutation.mutate({ id: campaign.id, name: campaign.name })
    },
  })

  // The release path: back to a plain Library row, stage discarded,
  // re-pullable -- vs. the campaign path above, which parks re-pull-
  // protected with the stage snapshotted.
  const removeMutation = useMutation({
    mutationFn: () => removeFromPipeline(Array.from(selectedIds)),
    onSuccess: (res) => {
      setResult(`Moved ${res.removed} school${res.removed === 1 ? "" : "s"} back to the Library`)
      clear()
      queryClient.invalidateQueries({ queryKey: ["schools"] })
      invalidateAfterBulkChange(queryClient)
    },
  })

  function handleRemoveSelected() {
    if (
      !window.confirm(
        `Move ${selectedIds.size} school${selectedIds.size === 1 ? "" : "s"} back to the Library? They leave the pipeline and their stage is discarded — a later re-pull starts over at "Not contacted". (To park a finished batch and protect it from re-pulls, use "Move to campaign" instead.)`
      )
    ) {
      return
    }
    removeMutation.mutate()
  }

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

      {!addingCampaign ? (
        <div className="flex items-center gap-2">
          <select
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={campaignChoice}
            onChange={(e) => setCampaignChoice(e.target.value)}
          >
            <option value="">Choose campaign&hellip;</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.school_count})
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={campaignChoice === "" || campaignMutation.isPending}
            title="Moves the selected schools OUT of the pipeline and into this campaign"
            onClick={() => {
              const campaign = campaigns.find((c) => c.id === Number(campaignChoice))
              if (campaign) campaignMutation.mutate(campaign)
            }}
          >
            <Archive className="h-3.5 w-3.5" />
            Move to campaign
          </Button>
          <button
            type="button"
            className="text-xs text-[var(--color-accent)] hover:underline"
            onClick={() => setAddingCampaign(true)}
          >
            + New campaign
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <input
            type="text"
            autoFocus
            placeholder="New campaign name"
            className="w-40 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={newCampaignName}
            onChange={(e) => setNewCampaignName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newCampaignName.trim()) createAndMoveMutation.mutate(newCampaignName.trim())
              if (e.key === "Escape") setAddingCampaign(false)
            }}
          />
          <Button
            size="sm"
            disabled={!newCampaignName.trim() || createAndMoveMutation.isPending || campaignMutation.isPending}
            onClick={() => createAndMoveMutation.mutate(newCampaignName.trim())}
          >
            Create &amp; move
          </Button>
          <button type="button" className="text-xs text-[var(--color-text-muted)] hover:underline" onClick={() => setAddingCampaign(false)}>
            Cancel
          </button>
        </div>
      )}

      <span className="h-6 w-px bg-[var(--color-border)]" />

      <Button
        size="sm"
        disabled={removeMutation.isPending}
        title="Drop the selected schools from the pipeline back to plain Library rows — stage discarded, re-pullable later"
        onClick={handleRemoveSelected}
      >
        <BookMarked className="h-3.5 w-3.5" />
        Move to Library
      </Button>

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
