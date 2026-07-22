import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Search, ArrowRightCircle, CheckSquare, CheckSquare2, Sparkles, Download } from "lucide-react"
import { countSchools, listSchoolIds } from "@/api/schools"
import { pullIntoPipeline } from "@/api/pipeline"
import { startEnrichmentJob, startEnrichmentJobFromFilters } from "@/api/enrichment"
import { exportSchoolsCsvUrl } from "@/api/crm"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { useLibraryFilters } from "../useLibraryFilters"
import { useLibrarySelection } from "../useLibrarySelection"

const LARGE_BATCH_CONFIRM_THRESHOLD = 25

export function PreviewAndPullBar() {
  const { filters, sort, previewedCount, setPreviewedCount } = useLibraryFilters()
  const { selectedIds, setMany, clear: clearSelection } = useLibrarySelection()
  const [limit, setLimit] = useState<string>("")
  const [result, setResult] = useState<{ pulled_new: number; already_in_pipeline: number } | null>(null)
  const queryClient = useQueryClient()

  const previewMutation = useMutation({
    mutationFn: () => countSchools(filters),
    onSuccess: (count) => setPreviewedCount(count),
  })

  // Checkbox selection in the table below is scoped to whatever's on the
  // current page -- this resolves every id matching the current filters
  // server-side first (same query the count/pull/export actions already
  // use) and checks all of them at once, so hand-picking e.g. 200 schools
  // spread across 4 pages doesn't mean re-clicking "select all" 4 times.
  const selectAllMatchingMutation = useMutation({
    mutationFn: () => listSchoolIds(filters),
    onSuccess: (ids) => setMany(ids, true),
  })

  const pullMutation = useMutation({
    mutationFn: () =>
      pullIntoPipeline({ filters, limit: limit === "" ? null : Number(limit) }),
    onSuccess: (res) => {
      setResult(res)
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: ["schools"] })
    },
  })

  const pullSelectedMutation = useMutation({
    mutationFn: () => pullIntoPipeline({ schoolIds: Array.from(selectedIds) }),
    onSuccess: (res) => {
      setResult(res)
      clearSelection()
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: ["schools"] })
    },
  })

  const enrichSelectedMutation = useMutation({
    mutationFn: () => startEnrichmentJob(Array.from(selectedIds)),
    onSuccess: () => {
      clearSelection()
      queryClient.invalidateQueries({ queryKey: queryKeys.enrichmentJobs() })
    },
  })

  const enrichAllMutation = useMutation({
    mutationFn: () => startEnrichmentJobFromFilters(filters, limit === "" ? null : Number(limit)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.enrichmentJobs() })
    },
  })

  function handleEnrichAll() {
    if (previewedCount === null) return
    const parsedLimit = limit === "" ? null : Number(limit)
    const effective = parsedLimit === null ? previewedCount : Math.min(previewedCount, parsedLimit)
    if (
      effective > LARGE_BATCH_CONFIRM_THRESHOLD &&
      !window.confirm(
        `Enrich ${effective.toLocaleString()} schools matching the current filters? Each one crawls its website and, if needed, runs a web search -- this can take a while and may hit search rate limits for very large batches.`
      )
    ) {
      return
    }
    enrichAllMutation.mutate()
  }

  function handleEnrichSelected() {
    if (
      selectedIds.size > LARGE_BATCH_CONFIRM_THRESHOLD &&
      !window.confirm(
        `Enrich ${selectedIds.size} schools? Each one crawls its website and, if needed, runs a web search -- this can take a while and may hit search rate limits for very large batches.`
      )
    ) {
      return
    }
    enrichSelectedMutation.mutate()
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center gap-1.5">
        <label className="whitespace-nowrap text-xs font-medium text-[var(--color-text-muted)]"># schools</label>
        <input
          type="number"
          placeholder="All matching"
          className="w-28 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={limit}
          onChange={(e) => setLimit(e.target.value)}
        />
      </div>

      <Button onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending}>
        <Search className="h-4 w-4" />
        Preview count
      </Button>

      {previewedCount !== null && (
        <span className="text-sm text-[var(--color-text-muted)]">
          <strong className="text-[var(--color-text)]">{previewedCount.toLocaleString()}</strong> schools match
        </span>
      )}

      <Button
        variant="primary"
        disabled={previewedCount === null || pullMutation.isPending}
        onClick={() => pullMutation.mutate()}
        title={previewedCount === null ? "Run Preview count first" : undefined}
      >
        <ArrowRightCircle className="h-4 w-4" />
        Pull into pipeline
      </Button>

      <Button
        disabled={previewedCount === null || enrichAllMutation.isPending}
        onClick={handleEnrichAll}
        title={previewedCount === null ? "Run Preview count first" : undefined}
      >
        <Sparkles className="h-4 w-4" />
        Enrich all matching
      </Button>

      <span className="h-6 w-px bg-[var(--color-border)]" />

      <Button
        disabled={previewedCount === null || selectAllMatchingMutation.isPending}
        onClick={() => selectAllMatchingMutation.mutate()}
        title={previewedCount === null ? "Run Preview count first" : "Check every school matching the current filters, across all pages"}
      >
        <CheckSquare2 className="h-4 w-4" />
        Select all matching{previewedCount !== null && ` (${previewedCount.toLocaleString()})`}
      </Button>

      <Button
        variant="primary"
        disabled={selectedIds.size === 0 || pullSelectedMutation.isPending}
        onClick={() => pullSelectedMutation.mutate()}
        title={selectedIds.size === 0 ? "Select schools in the table below first" : undefined}
      >
        <CheckSquare className="h-4 w-4" />
        Pull selected {selectedIds.size > 0 && `(${selectedIds.size})`}
      </Button>

      <Button
        disabled={selectedIds.size === 0 || enrichSelectedMutation.isPending}
        onClick={handleEnrichSelected}
        title={selectedIds.size === 0 ? "Select schools in the table below first" : undefined}
      >
        <Sparkles className="h-4 w-4" />
        Enrich selected {selectedIds.size > 0 && `(${selectedIds.size})`}
      </Button>

      <span className="h-6 w-px bg-[var(--color-border)]" />

      <a
        href={exportSchoolsCsvUrl(filters, sort)}
        download
        className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 py-2 text-sm font-medium text-[var(--color-text)] transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
      >
        <Download className="h-4 w-4" />
        Export CSV
      </a>

      {(enrichSelectedMutation.isSuccess || enrichAllMutation.isSuccess) && (
        <span className="text-sm text-green-600">Enrichment started &mdash; see the tray in the corner.</span>
      )}

      {result && (
        <span className="text-sm text-green-600">
          Pulled {result.pulled_new} new{result.already_in_pipeline > 0 && ` (${result.already_in_pipeline} already in pipeline)`}
        </span>
      )}
    </div>
  )
}
