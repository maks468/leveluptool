import {
  useState,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
  type DragEvent as ReactDragEvent,
} from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search, ArrowDown, ArrowUp, ArrowUpDown, Sparkles, Download, X } from "lucide-react"
import { listPipeline, listPipelineIds, exportPipelineCsvUrl } from "@/api/pipeline"
import { startEnrichmentJob } from "@/api/enrichment"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { PIPELINE_STAGES, STAGE_LABELS, type PipelineStage } from "@/types/domain"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { ScoreBadge } from "@/components/shared/ScoreBadge"
import { EnrichmentLevelBadge } from "@/components/shared/EnrichmentLevelBadge"
import { StagePill } from "@/components/shared/StagePill"
import { Badge } from "@/components/ui/Badge"
import { useMoveStageMutation } from "../useMoveStageMutation"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"
import { PaginationControls } from "@/components/shared/PaginationControls"
import { shortenSchoolName } from "@/lib/schoolName"
import { cn } from "@/lib/utils"
import { PipelineFiltersBar, type PipelineFilterState, type PipelineFiltersSnapshot } from "./PipelineFiltersBar"
import { PipelineBulkActionBar } from "./PipelineBulkActionBar"
import { PipelineSavedViewsBar } from "./PipelineSavedViewsBar"
import { PipelineColumnManager } from "./PipelineColumnManager"
import {
  usePipelineColumns,
  DEFAULT_COLUMN_WIDTH,
  DEFAULT_NAME_WIDTH,
  type PipelineColumnKey,
} from "../usePipelineColumns"
import type { PipelineSchool } from "@/types/domain"

const PAGE_SIZE = 100

const LARGE_BATCH_CONFIRM_THRESHOLD = 25

type SortField = "name" | "city" | "students" | "score" | "stage_updated_at" | "next_action_date"
type SortDirection = "asc" | "desc"

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleDateString()
}

/** One entry per manageable column (see usePipelineColumns) -- `label` and
 * an optional `sortField` (omit for columns that can't be sorted) drive the
 * shared header renderer below; `cell` renders just the inner content of
 * the row's <td> (the render loop supplies the consistent <td> wrapper).
 * Adding a column here never means touching the render/drag/resize logic
 * itself. */
const COLUMN_REGISTRY: Record<
  PipelineColumnKey,
  { label: string; sortField?: SortField; cell: (school: PipelineSchool) => ReactNode }
> = {
  city: {
    label: "City",
    sortField: "city",
    cell: (school) => <DataValueCell value={school.city} />,
  },
  director: {
    label: "Director",
    cell: (school) => <DataValueCell value={school.director_name} />,
  },
  teacher: {
    label: "English teacher",
    cell: (school) => <DataValueCell value={school.english_teacher_name} />,
  },
  website: {
    label: "Website",
    cell: (school) =>
      school.website_url ? (
        <a
          href={school.website_url.startsWith("http") ? school.website_url : `https://${school.website_url}`}
          target="_blank"
          rel="noopener noreferrer"
          className="truncate text-[var(--color-accent)] hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {school.website_url}
        </a>
      ) : (
        <DataValueCell value={null} />
      ),
  },
  best_email: {
    label: "Best email",
    cell: (school) =>
      school.best_email ? (
        <a
          href={`mailto:${school.best_email}`}
          className="text-[var(--color-accent)] hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {school.best_email}
        </a>
      ) : (
        <DataValueCell value={null} />
      ),
  },
  stage: {
    label: "Stage",
    cell: (school) => <StagePill stage={school.stage} />,
  },
  students: {
    label: "Students",
    sortField: "students",
    cell: (school) => <DataValueCell value={school.student_count} />,
  },
  score: {
    label: "Score",
    sortField: "score",
    cell: (school) => <ScoreBadge score={school.score} />,
  },
  enrichment: {
    label: "Enrichment",
    cell: (school) => <EnrichmentLevelBadge level={school.enrichment_level} />,
  },
  next_follow_up: {
    label: "Next follow-up",
    sortField: "next_action_date",
    cell: (school) => formatDate(school.next_action_date),
  },
  stage_updated: {
    label: "Stage updated",
    sortField: "stage_updated_at",
    cell: (school) => formatDate(school.stage_updated_at),
  },
  added_via: {
    label: "Added via",
    cell: (school) => (
      <span className="block max-w-[220px] truncate" title={school.pull_criteria ?? undefined}>
        {school.pull_criteria ?? "—"}
      </span>
    ),
  },
}

/** A grabbable strip on a header's right edge -- drag it to resize that
 * column. Pointer capture means the drag keeps tracking even if the
 * cursor slips off the 6px strip mid-drag, which a plain mousemove
 * listener on the handle itself wouldn't survive. stopPropagation on
 * pointerdown keeps this from also starting the header's own
 * drag-to-reorder gesture. */
function ColumnResizeHandle({ width, onResize }: { width: number; onResize: (px: number) => void }) {
  function handlePointerDown(e: ReactPointerEvent<HTMLSpanElement>) {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startWidth = width
    const handle = e.currentTarget
    handle.setPointerCapture(e.pointerId)

    function handleMove(ev: PointerEvent) {
      onResize(startWidth + (ev.clientX - startX))
    }
    function handleUp() {
      window.removeEventListener("pointermove", handleMove)
      window.removeEventListener("pointerup", handleUp)
    }
    window.addEventListener("pointermove", handleMove)
    window.addEventListener("pointerup", handleUp)
  }

  return (
    <span
      onPointerDown={handlePointerDown}
      onClick={(e) => e.stopPropagation()}
      draggable={false}
      className="absolute right-0 top-0 z-10 h-full w-1.5 cursor-col-resize select-none hover:bg-[var(--color-accent)]/50 active:bg-[var(--color-accent)]"
    />
  )
}

const DEFAULT_FILTERS: PipelineFilterState = {
  voivodeship: null,
  city: null,
  tagId: null,
  schoolType: "all",
  ownership: "all",
  studentsMin: null,
  studentsMax: null,
  scoreMin: null,
  scoreMax: null,
  scoreIncludeUnscored: true,
  enrichmentLevel: null,
}

/** One independent, self-contained slice of the Pipeline -- its own
 * search/filters/sort/selection/pagination. Rendering more than one of
 * these side by side (see PipelinePage) is what gives "multiple windows
 * into the pipeline" -- each can show a different saved view or ad hoc
 * filter combo without the panels fighting over shared state. */
export function PipelinePanel({
  onClose,
  panelLabel,
}: {
  onClose?: () => void
  panelLabel?: string
}) {
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [search, setSearch] = useState("")
  const [stageFilter, setStageFilter] = useState<PipelineStage | "all">("all")
  const [filters, setFilters] = useState<PipelineFilterState>(DEFAULT_FILTERS)
  const [sortField, setSortField] = useState<SortField>("stage_updated_at")
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc")
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const { order: columnOrder, hidden: hiddenColumns, widths: columnWidths, reorder, setWidth } = usePipelineColumns()
  const [draggingColumn, setDraggingColumn] = useState<PipelineColumnKey | null>(null)
  const visibleColumns = columnOrder.filter((key) => !hiddenColumns.includes(key))
  const columnCount = visibleColumns.length + 3 // checkbox + Name + Change-stage are always present
  const nameWidth = columnWidths.name ?? DEFAULT_NAME_WIDTH
  const tableWidth =
    40 + nameWidth + visibleColumns.reduce((sum, key) => sum + (columnWidths[key] ?? DEFAULT_COLUMN_WIDTH), 0) + 140

  /** The sort button shared by every sortable header (registry columns and
   * the fixed Name column alike) -- just the button, not the <th> itself,
   * since the two callers wrap it differently (Name is fixed-position and
   * not draggable; registry columns are both draggable and resizable). */
  function renderSortLabel(label: string, field: SortField) {
    const active = sortField === field
    return (
      <button
        type="button"
        onClick={() => handleSort(field)}
        className={cn(
          "flex items-center gap-1 font-medium",
          active ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
        )}
      >
        {label}
        {active ? (
          sortDirection === "asc" ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" />
        )}
      </button>
    )
  }

  function renderHeaderCell(key: PipelineColumnKey) {
    const col = COLUMN_REGISTRY[key]
    const width = columnWidths[key] ?? DEFAULT_COLUMN_WIDTH
    return (
      <th
        key={key}
        draggable
        onDragStart={() => setDraggingColumn(key)}
        onDragOver={(e: ReactDragEvent) => e.preventDefault()}
        onDrop={() => {
          if (draggingColumn) reorder(draggingColumn, key)
          setDraggingColumn(null)
        }}
        onDragEnd={() => setDraggingColumn(null)}
        className={cn(
          "relative whitespace-nowrap border-b border-[var(--color-border)] px-3 py-2 cursor-grab select-none active:cursor-grabbing",
          draggingColumn === key && "opacity-40"
        )}
      >
        {col.sortField ? renderSortLabel(col.label, col.sortField) : col.label}
        <ColumnResizeHandle width={width} onResize={(px) => setWidth(key, px)} />
      </th>
    )
  }

  const sort = `${sortField}:${sortDirection}`
  const stage = stageFilter === "all" ? undefined : stageFilter

  const queryArgs = {
    page,
    pageSize: PAGE_SIZE,
    stage,
    q: search || undefined,
    voivodeship: filters.voivodeship,
    city: filters.city,
    tagId: filters.tagId,
    schoolType: filters.schoolType,
    ownership: filters.ownership,
    studentsMin: filters.studentsMin,
    studentsMax: filters.studentsMax,
    scoreMin: filters.scoreMin,
    scoreMax: filters.scoreMax,
    scoreIncludeUnscored: filters.scoreIncludeUnscored,
    enrichmentLevel: filters.enrichmentLevel,
    sort,
  }

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.pipeline(queryArgs),
    queryFn: () => listPipeline(queryArgs),
  })
  const schools = data?.items ?? []
  const moveStage = useMoveStageMutation()
  const pageIds = schools.map((s) => s.id)
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id))

  const queryClient = useQueryClient()
  // Enriches EVERY school matching the current filters, across all pages --
  // resolves the full id set server-side first (not just the visible page),
  // then fires one enrichment job for the lot.
  const enrichAllMutation = useMutation({
    mutationFn: async () => {
      const ids = await listPipelineIds(queryArgs)
      if (ids.length > 0) await startEnrichmentJob(ids)
      return ids.length
    },
    onSuccess: (started) => {
      if (started > 0) queryClient.invalidateQueries({ queryKey: queryKeys.enrichmentJobs() })
    },
  })

  function handleEnrichAll() {
    const count = data?.total ?? 0
    if (count === 0) return
    if (
      count > LARGE_BATCH_CONFIRM_THRESHOLD &&
      !window.confirm(
        `Enrich all ${count.toLocaleString()} schools in this pipeline view? Each one crawls its website and, if needed, runs a web search -- this can take a while and may hit search rate limits for very large batches.`
      )
    ) {
      return
    }
    enrichAllMutation.mutate()
  }

  function toggleSelected(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function setManySelected(ids: number[], selected: boolean) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      for (const id of ids) {
        if (selected) next.add(id)
        else next.delete(id)
      }
      return next
    })
  }

  function handleFilterChange(patch: Partial<PipelineFilterState>) {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(1)
  }

  function handleSort(field: SortField) {
    if (field === sortField) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDirection(field === "name" || field === "city" ? "asc" : "desc")
    }
    setPage(1)
  }

  function handleApplySavedView(snapshot: PipelineFiltersSnapshot, savedSort: string | null) {
    setStageFilter(snapshot.stage)
    // Merged over the defaults: a view saved before a filter existed has no
    // value for it, and the default is the only sensible reading of "the
    // person who saved this never chose one".
    const { stage: _stage, ...savedFilters } = snapshot
    setFilters({ ...DEFAULT_FILTERS, ...savedFilters })
    if (savedSort) {
      const [field, direction] = savedSort.split(":")
      setSortField((field as SortField) || "stage_updated_at")
      setSortDirection(direction === "asc" ? "asc" : "desc")
    }
    setPage(1)
  }

  const totalInPipeline = data ? Object.values(data.stage_counts).reduce((a, b) => a + b, 0) : 0
  const snapshot: PipelineFiltersSnapshot = { stage: stageFilter, ...filters }

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col gap-3">
      {onClose && (
        <div className="flex flex-shrink-0 items-center justify-between">
          <span className="text-sm font-medium text-[var(--color-text-muted)]">{panelLabel ?? "Panel"}</span>
          <button
            type="button"
            className="rounded-md p-1 text-[var(--color-text-muted)] hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Close this panel"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
        <div className="flex min-w-64 flex-1 items-center gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5">
          <Search className="h-4 w-4 flex-shrink-0 text-[var(--color-text-muted)]" />
          <input
            type="text"
            placeholder="Search by school name or city..."
            className="w-full bg-transparent text-sm outline-none"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
          />
        </div>
        <Button
          className="flex-shrink-0"
          disabled={(data?.total ?? 0) === 0 || enrichAllMutation.isPending}
          onClick={handleEnrichAll}
          title="Enrich every school matching the current filters — all pages, not just this one"
        >
          <Sparkles className="h-4 w-4" />
          {enrichAllMutation.isPending ? "Enriching…" : `Enrich all${data ? ` (${data.total.toLocaleString()})` : ""}`}
        </Button>
        <a
          href={exportPipelineCsvUrl(queryArgs)}
          download
          className="inline-flex flex-shrink-0 items-center justify-center gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3.5 py-2 text-sm font-medium text-[var(--color-text)] transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
          title="Export every school matching the current filters — all pages, not just this one"
        >
          <Download className="h-4 w-4" />
          Export CSV
        </a>
        <PipelineColumnManager />
        {enrichAllMutation.isSuccess && (
          <span className="text-sm text-green-600">Enrichment started &mdash; see the tray in the corner.</span>
        )}
      </div>

      <PipelineSavedViewsBar snapshot={snapshot} sort={sort} onApply={handleApplySavedView} />

      <PipelineFiltersBar
        filters={filters}
        onChange={handleFilterChange}
        stage={stageFilter}
        onStageChange={(s) => {
          setStageFilter(s)
          setPage(1)
        }}
        stageCounts={data?.stage_counts ?? {}}
        totalInPipeline={totalInPipeline}
      />

      <PipelineBulkActionBar selectedIds={selectedIds} clear={() => setSelectedIds(new Set())} />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="min-h-0 flex-1 overflow-auto">
        <table className="text-sm" style={{ width: tableWidth, tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: 40 }} />
            <col style={{ width: nameWidth }} />
            {visibleColumns.map((key) => (
              <col key={key} style={{ width: columnWidths[key] ?? DEFAULT_COLUMN_WIDTH }} />
            ))}
            <col style={{ width: 140 }} />
          </colgroup>
          <thead className="sticky top-0 z-10 bg-[var(--color-surface)]">
            <tr className="text-left text-xs text-[var(--color-text-muted)]">
              <th className="whitespace-nowrap border-b border-[var(--color-border)] px-3 py-2">
                <input
                  type="checkbox"
                  checked={allOnPageSelected}
                  onChange={(e) => setManySelected(pageIds, e.target.checked)}
                />
              </th>
              <th className="relative whitespace-nowrap border-b border-[var(--color-border)] px-3 py-2">
                {renderSortLabel("Name", "name")}
                <ColumnResizeHandle width={nameWidth} onResize={(px) => setWidth("name", px)} />
              </th>
              {visibleColumns.map(renderHeaderCell)}
              <th className="whitespace-nowrap border-b border-[var(--color-border)] px-3 py-2">Change stage</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={columnCount} className="px-3 py-6 text-center text-[var(--color-text-muted)]">
                  Loading&hellip;
                </td>
              </tr>
            )}
            {!isLoading && schools.length === 0 && (
              <tr>
                <td colSpan={columnCount} className="px-3 py-6 text-center text-[var(--color-text-muted)]">
                  No pipeline schools match this filter.
                </td>
              </tr>
            )}
            {schools.map((school, i) => (
              <tr
                key={school.id}
                className={cn(
                  "border-b border-[var(--color-border)] last:border-0 hover:bg-slate-100 dark:hover:bg-slate-800/60",
                  i % 2 === 1 && "bg-slate-50/60 dark:bg-slate-900/30"
                )}
              >
                <td className="whitespace-nowrap border-r border-[var(--color-border)] px-3 py-1.5">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(school.id)}
                    onChange={() => toggleSelected(school.id)}
                  />
                </td>
                <td
                  className="cursor-pointer overflow-hidden text-ellipsis whitespace-nowrap border-r border-[var(--color-border)] px-3 py-1.5 font-medium"
                  title={school.name}
                  onClick={() => setSelectedId(school.id)}
                >
                  {shortenSchoolName(school.name, school.city, school.name_disambiguator)}
                  {school.specialty && (
                    <Badge color="purple" className="ml-2" title={school.specialty}>
                      {school.specialty}
                    </Badge>
                  )}
                </td>
                {visibleColumns.map((key) => (
                  <td
                    key={key}
                    className="overflow-hidden text-ellipsis whitespace-nowrap border-r border-[var(--color-border)] px-3 py-1.5"
                  >
                    {COLUMN_REGISTRY[key].cell(school)}
                  </td>
                ))}
                <td className="whitespace-nowrap px-3 py-1.5">
                  <select
                    className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-xs"
                    value={school.stage}
                    onChange={(e) =>
                      moveStage.mutate({ schoolId: school.id, stage: e.target.value as PipelineStage })
                    }
                  >
                    {PIPELINE_STAGES.map((s) => (
                      <option key={s} value={s}>
                        {STAGE_LABELS[s]}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>

        {data && (
          <PaginationControls
            page={page}
            pageSize={PAGE_SIZE}
            total={data.total}
            onPageChange={setPage}
            itemLabel="in pipeline"
          />
        )}
      </div>

      {selectedId !== null && <SchoolDetailDrawer schoolId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
