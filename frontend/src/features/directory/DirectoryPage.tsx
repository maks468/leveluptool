import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { listCities, listDirectory, listVoivodeships } from "@/api/schools"
import { listCampaigns } from "@/api/campaigns"
import { queryKeys } from "@/api/queryKeys"
import { Badge } from "@/components/ui/Badge"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { StagePill } from "@/components/shared/StagePill"
import { PaginationControls } from "@/components/shared/PaginationControls"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"
import { shortenSchoolName } from "@/lib/schoolName"
import { LEVEL_LABELS, type DirectoryEntry, type DirectoryStatus } from "@/types/domain"

const PAGE_SIZE = 50

// Same vocabulary as the Library's panel, so the two pages read alike.
const SCHOOL_TYPE_OPTIONS = [
  { value: "all", label: "All types" },
  { value: "primary", label: "Primary" },
  { value: "secondary", label: "Secondary (liceum + technikum)" },
  { value: "liceum", label: "Liceum only" },
  { value: "technikum", label: "Technikum only" },
  { value: "vocational", label: "Vocational" },
] as const

const ENRICHMENT_OPTIONS = [
  { value: "all", label: "Any enrichment" },
  { value: "enriched", label: "Enriched — contacts found" },
  { value: "not_enriched", label: "Not enriched" },
  { value: "complete", label: "· Complete — teacher email" },
  { value: "successful", label: "· Successful — director email" },
  { value: "partial", label: "· Partial" },
  { value: "basic", label: "· Basic" },
  { value: "attempted", label: "Attempted" },
  { value: "never_attempted", label: "Never attempted" },
] as const

/** The full register, read-only: every school and where it currently
 * lives -- Available (still in the Library pool), Pipeline (with its
 * stage), or the campaign it's parked in. Nothing ever disappears from
 * here; it just changes status. All moving of schools happens on the
 * Library / Pipeline / Campaigns pages. */
export function DirectoryPage() {
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<"all" | DirectoryStatus>("all")
  const [campaignId, setCampaignId] = useState<number | null>(null)
  const [voivodeship, setVoivodeship] = useState<string | null>(null)
  const [city, setCity] = useState<string | null>(null)
  const [schoolType, setSchoolType] = useState("all")
  const [ownership, setOwnership] = useState<"all" | "public" | "private">("all")
  const [studentsMin, setStudentsMin] = useState<number | null>(null)
  const [studentsMax, setStudentsMax] = useState<number | null>(null)
  const [scoreMin, setScoreMin] = useState<number | null>(null)
  const [scoreMax, setScoreMax] = useState<number | null>(null)
  const [enrichment, setEnrichment] = useState("all")
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: campaigns = [] } = useQuery({ queryKey: queryKeys.campaigns(), queryFn: listCampaigns })
  // "register" scope: the Directory shows every school, so its region
  // dropdowns must list every region -- unlike the Library's, which are
  // scoped to the available pool.
  const { data: voivodeships = [] } = useQuery({
    queryKey: ["voivodeships", "register"],
    queryFn: () => listVoivodeships("register"),
  })
  const { data: cities = [] } = useQuery({
    queryKey: ["cities", voivodeship, "register"],
    queryFn: () => listCities(voivodeship, "register"),
  })

  const args = {
    q: search || undefined,
    status: campaignId !== null ? ("campaign" as const) : status,
    campaignId,
    voivodeship,
    city,
    schoolType,
    ownership,
    studentsMin,
    studentsMax,
    scoreMin,
    scoreMax,
    enrichment,
    page,
    pageSize: PAGE_SIZE,
  }
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.directory(args),
    queryFn: () => listDirectory(args),
  })

  function statusBadge(entry: DirectoryEntry) {
    if (entry.status === "campaign") {
      return (
        <Badge color="cyan" title={`Parked in campaign "${entry.campaign_name}"`}>
          {entry.campaign_name}
        </Badge>
      )
    }
    if (entry.status === "pipeline" && entry.stage) {
      return <StagePill stage={entry.stage} />
    }
    return <Badge color="green" variant="dashed">Available</Badge>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Directory</h1>
          <p className="text-xs text-[var(--color-text-muted)]">
            Every school in the register and where it currently lives. Read-only &mdash; schools are moved from the
            Library, Pipeline and Campaigns pages.
          </p>
        </div>
        {data && (
          <span className="text-xs text-[var(--color-text-muted)]">
            {data.register_total.toLocaleString()} matching &middot; {data.counts.available.toLocaleString()} available
            &middot; {data.counts.pipeline.toLocaleString()} in pipeline &middot;{" "}
            {data.counts.campaign.toLocaleString()} in campaigns
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
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
        <select
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={campaignId !== null ? `campaign:${campaignId}` : status}
          onChange={(e) => {
            const v = e.target.value
            if (v.startsWith("campaign:")) {
              setCampaignId(Number(v.split(":")[1]))
              setStatus("campaign")
            } else {
              setCampaignId(null)
              setStatus(v as "all" | DirectoryStatus)
            }
            setPage(1)
          }}
        >
          <option value="all">All schools{data ? ` (${data.register_total.toLocaleString()})` : ""}</option>
          <option value="available">Available{data ? ` (${data.counts.available.toLocaleString()})` : ""}</option>
          <option value="pipeline">In pipeline{data ? ` (${data.counts.pipeline.toLocaleString()})` : ""}</option>
          <option value="campaign">In any campaign{data ? ` (${data.counts.campaign.toLocaleString()})` : ""}</option>
          {campaigns.map((c) => (
            <option key={c.id} value={`campaign:${c.id}`}>
              &nbsp;&nbsp;{c.name} ({c.school_count})
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={voivodeship ?? ""}
          onChange={(e) => { setVoivodeship(e.target.value || null); setCity(null); setPage(1) }}
        >
          <option value="">Any voivodeship</option>
          {voivodeships.map((v) => (
            <option key={v.voivodeship} value={v.voivodeship}>{v.voivodeship}</option>
          ))}
        </select>
        <select
          className="max-w-44 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={city ?? ""}
          onChange={(e) => { setCity(e.target.value || null); setPage(1) }}
        >
          <option value="">Any city</option>
          {cities.map((c) => (
            <option key={c.city} value={c.city}>{c.city}</option>
          ))}
        </select>
        <select
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={schoolType}
          onChange={(e) => { setSchoolType(e.target.value); setPage(1) }}
        >
          {SCHOOL_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <select
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={ownership}
          onChange={(e) => { setOwnership(e.target.value as typeof ownership); setPage(1) }}
        >
          <option value="all">Any ownership</option>
          <option value="public">Public</option>
          <option value="private">Private</option>
        </select>
        <div className="flex items-center gap-1 text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">Students</span>
          <input type="number" placeholder="Min" min={0}
            className="w-16 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={studentsMin ?? ""}
            onChange={(e) => { setStudentsMin(e.target.value === "" ? null : Number(e.target.value)); setPage(1) }} />
          <span className="text-[var(--color-text-muted)]">–</span>
          <input type="number" placeholder="Max" min={0}
            className="w-16 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={studentsMax ?? ""}
            onChange={(e) => { setStudentsMax(e.target.value === "" ? null : Number(e.target.value)); setPage(1) }} />
        </div>
        <div className="flex items-center gap-1 text-sm">
          <span className="text-xs text-[var(--color-text-muted)]">Score</span>
          <input type="number" placeholder="Min" min={0} max={100}
            className="w-16 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={scoreMin ?? ""}
            onChange={(e) => { setScoreMin(e.target.value === "" ? null : Number(e.target.value)); setPage(1) }} />
          <span className="text-[var(--color-text-muted)]">–</span>
          <input type="number" placeholder="Max" min={0} max={100}
            className="w-16 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={scoreMax ?? ""}
            onChange={(e) => { setScoreMax(e.target.value === "" ? null : Number(e.target.value)); setPage(1) }} />
        </div>
        <select
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={enrichment}
          onChange={(e) => { setEnrichment(e.target.value); setPage(1) }}
        >
          {ENRICHMENT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        {(voivodeship || city || schoolType !== "all" || ownership !== "all" || studentsMin !== null ||
          studentsMax !== null || scoreMin !== null || scoreMax !== null || enrichment !== "all") && (
          <button
            type="button"
            className="text-xs text-[var(--color-accent)] hover:underline"
            onClick={() => {
              setVoivodeship(null); setCity(null); setSchoolType("all"); setOwnership("all")
              setStudentsMin(null); setStudentsMax(null); setScoreMin(null); setScoreMax(null)
              setEnrichment("all"); setPage(1)
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Level</th>
              <th className="px-3 py-2">City</th>
              <th className="px-3 py-2">Voivodeship</th>
              <th className="px-3 py-2">Score</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-[var(--color-text-muted)]">
                  Loading&hellip;
                </td>
              </tr>
            )}
            {!isLoading && data?.items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-[var(--color-text-muted)]">
                  No schools match.
                </td>
              </tr>
            )}
            {data?.items.map((entry) => (
              <tr
                key={entry.id}
                className="cursor-pointer border-b border-[var(--color-border)] last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                onClick={() => setSelectedId(entry.id)}
              >
                <td className="px-3 py-2 font-medium" title={entry.name}>
                  {shortenSchoolName(entry.name, entry.city, entry.name_disambiguator)}
                </td>
                <td className="px-3 py-2">{LEVEL_LABELS[entry.level]}</td>
                <td className="px-3 py-2">
                  <DataValueCell value={entry.city} />
                </td>
                <td className="px-3 py-2">
                  <DataValueCell value={entry.voivodeship} />
                </td>
                <td className="px-3 py-2">{entry.score !== null ? `${entry.score}/100` : "—"}</td>
                <td className="px-3 py-2">{statusBadge(entry)}</td>
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
