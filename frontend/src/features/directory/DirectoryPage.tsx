import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { listDirectory } from "@/api/schools"
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

/** The full register, read-only: every school and where it currently
 * lives -- Available (still in the Library pool), Pipeline (with its
 * stage), or the campaign it's parked in. Nothing ever disappears from
 * here; it just changes status. All moving of schools happens on the
 * Library / Pipeline / Campaigns pages. */
export function DirectoryPage() {
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<"all" | DirectoryStatus>("all")
  const [campaignId, setCampaignId] = useState<number | null>(null)
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const { data: campaigns = [] } = useQuery({ queryKey: queryKeys.campaigns(), queryFn: listCampaigns })

  const args = {
    q: search || undefined,
    status: campaignId !== null ? ("campaign" as const) : status,
    campaignId,
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
            {data.register_total.toLocaleString()} schools &middot; {data.counts.available.toLocaleString()} available
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
