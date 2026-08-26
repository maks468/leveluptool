import { useQuery } from "@tanstack/react-query"
import { listCities, listVoivodeships } from "@/api/schools"
import { useLibraryFilters } from "../useLibraryFilters"
import { OwnershipFilter } from "./OwnershipFilter"

const SCHOOL_TYPE_OPTIONS = [
  { value: "all", label: "All target types" },
  { value: "primary", label: "Primary (podstawówka)" },
  { value: "secondary", label: "Secondary (liceum + technikum)" },
  { value: "liceum", label: "Liceum only" },
  { value: "technikum", label: "Technikum only" },
  { value: "vocational", label: "Vocational (branżowa I/II + policealna)" },
] as const

// The first group asks what enrichment FOUND, in the same words the
// Enrichment column's badges use, so filtering and reading the results
// match. The last two ask the separate question of whether it ever RAN.
const ENRICHMENT_OPTIONS = [
  { value: "all", label: "Any" },
  { value: "enriched", label: "Enriched — contacts found" },
  { value: "not_enriched", label: "Not enriched — nothing found" },
  { value: "complete", label: "· Complete — teacher email" },
  { value: "successful", label: "· Successful — director email" },
  { value: "partial", label: "· Partial — teacher named" },
  { value: "basic", label: "· Basic — director + office email" },
  { value: "attempted", label: "Attempted — ran, any outcome" },
  { value: "never_attempted", label: "Never attempted" },
] as const

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: readonly { value: string; label: string }[]
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">{label}</label>
      <select
        className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}

export function QualificationFiltersPanel() {
  const { filters, set } = useLibraryFilters()

  const { data: voivodeships = [] } = useQuery({
    queryKey: ["voivodeships", "library"],
    queryFn: () => listVoivodeships("library"),
  })
  const { data: cities = [] } = useQuery({
    queryKey: ["cities", filters.voivodeship, "library"],
    queryFn: () => listCities(filters.voivodeship, "library"),
  })

  return (
    <div className="space-y-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="text-sm font-semibold">Qualification filters</h2>

      <Select
        label="Voivodeship"
        value={filters.voivodeship ?? ""}
        onChange={(v) => {
          set("voivodeship", v || null)
          set("city", null)
        }}
        options={[
          { value: "", label: "Any" },
          ...voivodeships.map((v) => ({
            value: v.voivodeship,
            label: `${v.voivodeship} (${v.count.toLocaleString()})`,
          })),
        ]}
      />

      <Select
        label="City"
        value={filters.city ?? ""}
        onChange={(v) => set("city", v || null)}
        options={[
          { value: "", label: "Any" },
          ...cities.map((c) => ({ value: c.city, label: `${c.city} (${c.count.toLocaleString()})` })),
        ]}
      />

      <Select
        label="School type"
        value={filters.school_type}
        onChange={(v) => set("school_type", v as typeof filters.school_type)}
        options={SCHOOL_TYPE_OPTIONS}
      />

      <OwnershipFilter />

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Students</label>
        <div className="flex items-center gap-2">
          <input
            type="number"
            placeholder="Min"
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.students_min ?? ""}
            onChange={(e) => set("students_min", e.target.value === "" ? null : Number(e.target.value))}
          />
          <span className="text-[var(--color-text-muted)]">&ndash;</span>
          <input
            type="number"
            placeholder="Max"
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.students_max ?? ""}
            onChange={(e) => set("students_max", e.target.value === "" ? null : Number(e.target.value))}
          />
        </div>
        <label className="mt-1.5 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
          <input
            type="checkbox"
            checked={filters.students_include_unknown}
            onChange={(e) => set("students_include_unknown", e.target.checked)}
          />
          Include schools with unknown student count
        </label>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Score</label>
        <div className="flex items-center gap-2">
          <input
            type="number"
            placeholder="Min"
            min={0}
            max={100}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.score_min ?? ""}
            onChange={(e) => set("score_min", e.target.value === "" ? null : Number(e.target.value))}
          />
          <span className="text-[var(--color-text-muted)]">&ndash;</span>
          <input
            type="number"
            placeholder="Max"
            min={0}
            max={100}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={filters.score_max ?? ""}
            onChange={(e) => set("score_max", e.target.value === "" ? null : Number(e.target.value))}
          />
        </div>
        <label className="mt-1.5 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
          <input
            type="checkbox"
            checked={filters.score_include_unscored}
            onChange={(e) => set("score_include_unscored", e.target.checked)}
          />
          Include unscored schools (vocational/policealna)
        </label>
      </div>

      {/* Not qualification criteria -- these two are about how far a school
          has already been worked, which is what narrows a nationwide list
          down to "what's actually left to do". */}
      <div className="space-y-4 border-t border-[var(--color-border)] pt-4">
        <h2 className="text-sm font-semibold">Progress</h2>

        <Select
          label="Enrichment"
          value={filters.enrichment}
          onChange={(v) => set("enrichment", v as typeof filters.enrichment)}
          options={ENRICHMENT_OPTIONS}
        />

        {/* The Library shows only unassigned schools now -- schools in the
            pipeline or a campaign live in the Directory tab, so the old
            Pipeline in/out filter has nothing left to select. */}
      </div>
    </div>
  )
}
