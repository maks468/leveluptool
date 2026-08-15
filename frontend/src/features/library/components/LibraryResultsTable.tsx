import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { listSchools } from "@/api/schools"
import { queryKeys } from "@/api/queryKeys"
import { useLibraryFilters } from "../useLibraryFilters"
import { useLibrarySelection } from "../useLibrarySelection"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { ScoreBadge } from "@/components/shared/ScoreBadge"
import { OwnershipBadge } from "@/components/shared/OwnershipBadge"
import { EnrichmentLevelBadge } from "@/components/shared/EnrichmentLevelBadge"
import { Badge } from "@/components/ui/Badge"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"
import { PaginationControls } from "@/components/shared/PaginationControls"
import { shortenSchoolName } from "@/lib/schoolName"
import { LEVEL_LABELS } from "@/types/domain"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 50

type SortField = "score" | "students" | "name"
type SortDirection = "asc" | "desc"

function SortableHeader({
  label,
  field,
  sortField,
  sortDirection,
  onSort,
}: {
  label: string
  field: SortField
  sortField: SortField
  sortDirection: SortDirection
  onSort: (field: SortField) => void
}) {
  const active = sortField === field
  return (
    <th className="px-3 py-2">
      <button
        type="button"
        onClick={() => onSort(field)}
        className={cn(
          "flex items-center gap-1 font-medium",
          active ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
        )}
        title={`Sort by ${label.toLowerCase()}`}
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
    </th>
  )
}

export function LibraryResultsTable() {
  const { filters, sort, resultLimit, setSort, setResultLimit } = useLibraryFilters()
  const { selectedIds, toggle, setMany } = useLibrarySelection()
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const [sortFieldRaw, sortDirectionRaw] = sort.split(":")
  const sortField = (sortFieldRaw as SortField) || "score"
  const sortDirection: SortDirection = sortDirectionRaw === "asc" ? "asc" : "desc"
  const resultLimitInput = resultLimit === null ? "" : String(resultLimit)

  function handleSort(field: SortField) {
    if (field === sortField) {
      setSort(`${field}:${sortDirection === "asc" ? "desc" : "asc"}`)
    } else {
      setSort(`${field}:${field === "name" ? "asc" : "desc"}`)
    }
    setPage(1)
  }

  const { data, isLoading } = useQuery({
    queryKey: [...queryKeys.schools(filters, page, sort), resultLimit],
    queryFn: () => listSchools(filters, page, PAGE_SIZE, sort, resultLimit),
  })

  const pageIds = data?.items.map((s) => s.id) ?? []
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selectedIds.has(id))

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-2 text-sm">
        <label className="text-[var(--color-text-muted)]">Show top</label>
        <input
          type="number"
          min={1}
          placeholder="All"
          className="w-20 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm"
          value={resultLimitInput}
          onChange={(e) => {
            const val = e.target.value
            setResultLimit(val === "" ? null : Number(val))
            setPage(1)
          }}
        />
        <span className="text-[var(--color-text-muted)]">
          by {sortField === "score" ? "highest score" : sortField === "students" ? "most students" : "name"}
        </span>
        {resultLimitInput !== "" && (
          <button
            type="button"
            className="text-xs text-[var(--color-accent)] hover:underline"
            onClick={() => setResultLimit(null)}
          >
            Clear
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
              <th className="px-3 py-2">
                <input
                  type="checkbox"
                  checked={allOnPageSelected}
                  onChange={(e) => setMany(pageIds, e.target.checked)}
                />
              </th>
              <SortableHeader
                label="Name"
                field="name"
                sortField={sortField}
                sortDirection={sortDirection}
                onSort={handleSort}
              />
              <th className="px-3 py-2">Level</th>
              <th className="px-3 py-2">City</th>
              <th className="px-3 py-2">Ownership</th>
              <SortableHeader
                label="Students"
                field="students"
                sortField={sortField}
                sortDirection={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                label="Score"
                field="score"
                sortField={sortField}
                sortDirection={sortDirection}
                onSort={handleSort}
              />
              <th className="px-3 py-2">Enrichment</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-[var(--color-text-muted)]">
                  Loading&hellip;
                </td>
              </tr>
            )}
            {!isLoading && data?.items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-[var(--color-text-muted)]">
                  No schools match these filters.
                </td>
              </tr>
            )}
            {data?.items.map((school) => (
              <tr
                key={school.id}
                className="cursor-pointer border-b border-[var(--color-border)] last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                onClick={() => setSelectedId(school.id)}
              >
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selectedIds.has(school.id)} onChange={() => toggle(school.id)} />
                </td>
                <td className="px-3 py-2 font-medium" title={school.name}>
                  {shortenSchoolName(school.name, school.city, school.name_disambiguator)}
                  {school.in_pipeline && (
                    <Badge color="indigo" className="ml-2">
                      In pipeline
                    </Badge>
                  )}
                  {school.campaign_name && (
                    <Badge color="cyan" className="ml-2" title={`Parked in campaign "${school.campaign_name}" — pull-into-pipeline skips it`}>
                      {school.campaign_name}
                    </Badge>
                  )}
                  {school.is_adult_education && (
                    <Badge color="amber" className="ml-2">
                      Adult education
                    </Badge>
                  )}
                  {school.specialty && (
                    <Badge color="purple" className="ml-2" title={school.specialty}>
                      {school.specialty}
                    </Badge>
                  )}
                </td>
                <td className="px-3 py-2">{LEVEL_LABELS[school.level]}</td>
                <td className="px-3 py-2">
                  <DataValueCell value={school.city} />
                </td>
                <td className="px-3 py-2">
                  <OwnershipBadge school={school} />
                </td>
                <td className="px-3 py-2">
                  <DataValueCell value={school.student_count} />
                </td>
                <td className="px-3 py-2">
                  <ScoreBadge score={school.score} />
                </td>
                <td className="px-3 py-2">
                  <EnrichmentLevelBadge level={school.enrichment_level} />
                </td>
                <td className="px-3 py-2 text-[var(--color-text-muted)]">View &rarr;</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && <PaginationControls page={page} pageSize={PAGE_SIZE} total={data.total} onPageChange={setPage} />}

      {selectedId !== null && <SchoolDetailDrawer schoolId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
