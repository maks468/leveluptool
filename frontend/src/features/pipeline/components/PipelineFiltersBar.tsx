import { useQuery } from "@tanstack/react-query"
import { listCities, listVoivodeships } from "@/api/schools"
import { listTags } from "@/api/crm"
import { queryKeys } from "@/api/queryKeys"
import { ENRICHMENT_LEVEL_CONFIG } from "@/components/shared/EnrichmentLevelBadge"
import { PIPELINE_STAGES, STAGE_LABELS, type EnrichmentLevel, type PipelineStage } from "@/types/domain"

const ENRICHMENT_LEVELS: EnrichmentLevel[] = ["not_enriched", "basic", "partial", "successful"]

// Mirrors the Library's school-type options -- the question doesn't change
// once a school is in the pipeline, only the population it's asked of.
const SCHOOL_TYPE_OPTIONS = [
  { value: "all", label: "All types" },
  { value: "primary", label: "Primary" },
  { value: "secondary", label: "Secondary (liceum + technikum)" },
  { value: "liceum", label: "Liceum only" },
  { value: "technikum", label: "Technikum only" },
  { value: "vocational", label: "Vocational" },
] as const

export interface PipelineFilterState {
  voivodeship: string | null
  city: string | null
  tagId: number | null
  schoolType: string
  ownership: "all" | "public" | "private"
  studentsMin: number | null
  studentsMax: number | null
  scoreMin: number | null
  scoreMax: number | null
  scoreIncludeUnscored: boolean
  enrichmentLevel: EnrichmentLevel | null
}

/** Everything a saved Pipeline view needs to restore -- PipelineFilterState
 * plus the stage tab, which is tracked as separate state from the rest of
 * the filters (it drives the Status dropdown, not this bar). */
export interface PipelineFiltersSnapshot extends PipelineFilterState {
  stage: PipelineStage | "all"
}

/** Status/voivodeship/city/score-range filters for the Pipeline table, all
 * as compact dropdowns rather than a wall of always-visible stage pills --
 * "which pipeline schools are in a given region/score band" is just as
 * common a question here as it is when qualifying new leads in the
 * Library, so the same filter dimensions apply. Counts are scoped to the
 * pipeline itself (via the API's scope=pipeline), not the whole 25k-school
 * registry, so they reflect what's actually sitting in the pipeline. */
export function PipelineFiltersBar({
  filters,
  onChange,
  stage,
  onStageChange,
  stageCounts,
  totalInPipeline,
}: {
  filters: PipelineFilterState
  onChange: (patch: Partial<PipelineFilterState>) => void
  stage: PipelineStage | "all"
  onStageChange: (stage: PipelineStage | "all") => void
  stageCounts: Partial<Record<PipelineStage, number>>
  totalInPipeline: number
}) {
  const { data: voivodeships = [] } = useQuery({
    queryKey: ["voivodeships", "pipeline"],
    queryFn: () => listVoivodeships("pipeline"),
  })
  const { data: cities = [] } = useQuery({
    queryKey: ["cities", filters.voivodeship, "pipeline"],
    queryFn: () => listCities(filters.voivodeship, "pipeline"),
  })
  const { data: tags = [] } = useQuery({ queryKey: queryKeys.tags(), queryFn: listTags })

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Status</label>
        <select
          className="w-48 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={stage}
          onChange={(e) => onStageChange(e.target.value as PipelineStage | "all")}
        >
          <option value="all">All ({totalInPipeline.toLocaleString()})</option>
          {PIPELINE_STAGES.map((s) => (
            <option key={s} value={s}>
              {STAGE_LABELS[s]} ({(stageCounts[s] ?? 0).toLocaleString()})
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Województwo</label>
        <select
          className="w-44 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={filters.voivodeship ?? ""}
          onChange={(e) => onChange({ voivodeship: e.target.value || null, city: null })}
        >
          <option value="">Any</option>
          {voivodeships.map((v) => (
            <option key={v.voivodeship} value={v.voivodeship}>
              {v.voivodeship} ({v.count.toLocaleString()})
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">City</label>
        <select
          className="w-44 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={filters.city ?? ""}
          onChange={(e) => onChange({ city: e.target.value || null })}
        >
          <option value="">Any</option>
          {cities.map((c) => (
            <option key={c.city} value={c.city}>
              {c.city} ({c.count.toLocaleString()})
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Tag</label>
        <select
          className="w-40 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={filters.tagId ?? ""}
          onChange={(e) => onChange({ tagId: e.target.value === "" ? null : Number(e.target.value) })}
        >
          <option value="">Any</option>
          {tags.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">School type</label>
        <select
          className="w-40 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={filters.schoolType}
          onChange={(e) => onChange({ schoolType: e.target.value })}
        >
          {SCHOOL_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Ownership</label>
        <select
          className="w-28 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={filters.ownership}
          onChange={(e) => onChange({ ownership: e.target.value as PipelineFilterState["ownership"] })}
        >
          <option value="all">Any</option>
          <option value="public">Public</option>
          <option value="private">Private</option>
        </select>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Students</label>
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            placeholder="Min"
            min={0}
            className="w-20 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.studentsMin ?? ""}
            onChange={(e) => onChange({ studentsMin: e.target.value === "" ? null : Number(e.target.value) })}
          />
          <span className="text-[var(--color-text-muted)]">&ndash;</span>
          <input
            type="number"
            placeholder="Max"
            min={0}
            className="w-20 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.studentsMax ?? ""}
            onChange={(e) => onChange({ studentsMax: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Score (0&ndash;100)</label>
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            placeholder="Min"
            min={0}
            max={100}
            className="w-20 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.scoreMin ?? ""}
            onChange={(e) => onChange({ scoreMin: e.target.value === "" ? null : Number(e.target.value) })}
          />
          <span className="text-[var(--color-text-muted)]">&ndash;</span>
          <input
            type="number"
            placeholder="Max"
            min={0}
            max={100}
            className="w-20 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.scoreMax ?? ""}
            onChange={(e) => onChange({ scoreMax: e.target.value === "" ? null : Number(e.target.value) })}
          />
        </div>
      </div>

      <label className="flex items-center gap-1.5 pb-1.5 text-xs text-[var(--color-text-muted)]">
        <input
          type="checkbox"
          checked={filters.scoreIncludeUnscored}
          onChange={(e) => onChange({ scoreIncludeUnscored: e.target.checked })}
        />
        Include unscored
      </label>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Enrichment</label>
        <select
          className="w-40 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={filters.enrichmentLevel ?? ""}
          onChange={(e) => onChange({ enrichmentLevel: e.target.value === "" ? null : (e.target.value as EnrichmentLevel) })}
        >
          <option value="">Any</option>
          {ENRICHMENT_LEVELS.map((level) => (
            <option key={level} value={level}>
              {ENRICHMENT_LEVEL_CONFIG[level].label}
            </option>
          ))}
        </select>
      </div>

      {(stage !== "all" ||
        filters.voivodeship ||
        filters.city ||
        filters.tagId !== null ||
        filters.schoolType !== "all" ||
        filters.ownership !== "all" ||
        filters.studentsMin !== null ||
        filters.studentsMax !== null ||
        filters.scoreMin !== null ||
        filters.scoreMax !== null ||
        filters.enrichmentLevel !== null) && (
        <button
          type="button"
          className="pb-1.5 text-xs text-[var(--color-accent)] hover:underline"
          onClick={() => {
            onStageChange("all")
            onChange({
              voivodeship: null,
              city: null,
              tagId: null,
              schoolType: "all",
              ownership: "all",
              studentsMin: null,
              studentsMax: null,
              scoreMin: null,
              scoreMax: null,
              enrichmentLevel: null,
            })
          }}
        >
          Clear filters
        </button>
      )}
    </div>
  )
}
