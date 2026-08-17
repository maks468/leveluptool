import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Archive, Download, Pencil, Plus, Trash2, Undo2 } from "lucide-react"
import {
  createCampaign,
  deleteCampaign,
  exportCampaignCsvUrl,
  getCampaign,
  listCampaigns,
  returnAllToPipeline,
  returnSchoolToPipeline,
  updateCampaign,
} from "@/api/campaigns"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { StagePill } from "@/components/shared/StagePill"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"
import { shortenSchoolName } from "@/lib/schoolName"
import { LEVEL_LABELS } from "@/types/domain"
import { cn } from "@/lib/utils"

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString()
}

/** Campaign containers -- named batches of schools parked OUT of the
 * pipeline, purely for tracking which schools went into which outreach
 * batch so none is ever doubled. Nothing is sent from here; the only
 * actions are creating containers, looking inside them, and the explicit
 * return-to-pipeline escape hatch. */
export function CampaignsPage() {
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null)
  const [newName, setNewName] = useState("")
  const [selectedSchoolId, setSelectedSchoolId] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const queryClient = useQueryClient()

  const { data: campaigns = [], isLoading } = useQuery({
    queryKey: queryKeys.campaigns(),
    queryFn: listCampaigns,
  })

  const activeCampaignId = selectedCampaignId ?? campaigns[0]?.id ?? null
  const { data: detail } = useQuery({
    queryKey: queryKeys.campaign(activeCampaignId ?? -1),
    queryFn: () => getCampaign(activeCampaignId as number),
    enabled: activeCampaignId !== null,
  })

  const createMutation = useMutation({
    mutationFn: () => createCampaign(newName.trim()),
    onSuccess: (campaign) => {
      setNewName("")
      setSelectedCampaignId(campaign.id)
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns() })
    },
  })

  const returnMutation = useMutation({
    mutationFn: (schoolId: number) => returnSchoolToPipeline(activeCampaignId as number, schoolId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns() })
      queryClient.invalidateQueries({ queryKey: ["campaign"] })
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: ["schools"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] })
    },
  })

  const updateMutation = useMutation({
    mutationFn: () =>
      updateCampaign(activeCampaignId as number, { name: editName.trim(), description: editDescription.trim() }),
    onSuccess: () => {
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns() })
      queryClient.invalidateQueries({ queryKey: ["campaign"] })
      queryClient.invalidateQueries({ queryKey: ["schools"] })  // Library badges show the campaign name
    },
  })

  function startEditing() {
    if (!detail) return
    setEditName(detail.name)
    setEditDescription(detail.description ?? "")
    setEditing(true)
  }

  const returnAllMutation = useMutation({
    mutationFn: (campaignId: number) => returnAllToPipeline(campaignId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns() })
      queryClient.invalidateQueries({ queryKey: ["campaign"] })
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: ["schools"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (campaignId: number) => deleteCampaign(campaignId),
    onSuccess: () => {
      setSelectedCampaignId(null)
      queryClient.invalidateQueries({ queryKey: queryKeys.campaigns() })
      queryClient.invalidateQueries({ queryKey: ["schools"] })
    },
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Campaigns</h1>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="New campaign name"
            className="w-56 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && newName.trim()) createMutation.mutate()
            }}
          />
          <Button size="sm" disabled={!newName.trim() || createMutation.isPending} onClick={() => createMutation.mutate()}>
            <Plus className="h-4 w-4" />
            Create campaign
          </Button>
        </div>
      </div>

      {createMutation.isError && (
        <p className="text-sm text-red-600">Couldn&rsquo;t create the campaign &mdash; a campaign with that name may already exist.</p>
      )}

      <p className="text-xs text-[var(--color-text-muted)]">
        A campaign is a storage container: schools moved here <strong>leave the pipeline</strong> and can&rsquo;t be
        pulled back in from the Library, so a batch is never contacted twice. Nothing is sent automatically. Select
        schools in the Pipeline and use &ldquo;Move to campaign&rdquo; to fill these.
      </p>

      {isLoading && <p className="text-sm text-[var(--color-text-muted)]">Loading&hellip;</p>}

      {!isLoading && campaigns.length === 0 && (
        <div className="rounded-lg border border-dashed border-[var(--color-border)] p-8 text-center text-sm text-[var(--color-text-muted)]">
          <Archive className="mx-auto mb-2 h-6 w-6 opacity-50" />
          No campaigns yet. Create one above, then move schools into it from the Pipeline&rsquo;s selection bar.
        </div>
      )}

      {campaigns.length > 0 && (
        <div className="grid grid-cols-[260px_1fr] gap-4">
          <div className="space-y-2">
            {campaigns.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelectedCampaignId(c.id)}
                className={cn(
                  "w-full rounded-lg border p-3 text-left transition-colors",
                  c.id === activeCampaignId
                    ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5"
                    : "border-[var(--color-border)] bg-[var(--color-surface)] hover:border-[var(--color-accent)]/50"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium" title={c.name}>
                    {c.name}
                  </span>
                  <Badge color="indigo">{c.school_count}</Badge>
                </div>
                <span className="mt-1 block text-xs text-[var(--color-text-muted)]">Created {formatDate(c.created_at)}</span>
              </button>
            ))}
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)]">
            {detail && (
              <>
                <div className="flex items-start justify-between gap-3 border-b border-[var(--color-border)] px-4 py-3">
                  {editing ? (
                    <div className="flex-1 space-y-2">
                      <input
                        type="text"
                        autoFocus
                        className="w-full max-w-md rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm font-semibold"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                      />
                      <textarea
                        placeholder="Description — what is this batch? (optional)"
                        rows={2}
                        className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
                        value={editDescription}
                        onChange={(e) => setEditDescription(e.target.value)}
                      />
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="primary"
                          disabled={!editName.trim() || updateMutation.isPending}
                          onClick={() => updateMutation.mutate()}
                        >
                          {updateMutation.isPending ? "Saving…" : "Save"}
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
                          Cancel
                        </Button>
                        {updateMutation.isError && (
                          <span className="text-xs text-red-600">
                            Couldn&rsquo;t save &mdash; is that name already taken?
                          </span>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <h2 className="truncate text-sm font-semibold">{detail.name}</h2>
                        <button
                          type="button"
                          title="Rename or edit the description"
                          className="rounded p-0.5 text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                          onClick={startEditing}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      {detail.description && (
                        <p className="mt-0.5 max-w-xl whitespace-pre-wrap text-xs text-[var(--color-text)]">
                          {detail.description}
                        </p>
                      )}
                      <span className="text-xs text-[var(--color-text-muted)]">
                        {detail.school_count.toLocaleString()} school{detail.school_count === 1 ? "" : "s"} &middot;
                        created {formatDate(detail.created_at)}
                      </span>
                    </div>
                  )}
                  <div className="flex flex-shrink-0 items-center gap-2">
                  <a
                    href={exportCampaignCsvUrl(detail.id)}
                    download
                    title="Download this campaign's schools as CSV (includes best email, stage when moved, date added)"
                    className="inline-flex items-center justify-center gap-1.5 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm font-medium text-[var(--color-text)] transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Export CSV
                  </a>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={detail.school_count === 0 || returnAllMutation.isPending}
                    title="Puts every school in this campaign back into the pipeline, each at the stage it had when it was moved here"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Return all ${detail.school_count} schools from "${detail.name}" to the pipeline? Each goes back at the stage it had when it was moved here. The empty campaign stays until you delete it.`
                        )
                      ) {
                        returnAllMutation.mutate(detail.id)
                      }
                    }}
                  >
                    <Undo2 className="h-3.5 w-3.5" />
                    Return all to pipeline
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={deleteMutation.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete the campaign "${detail.name}"? Its ${detail.school_count} schools return to being plain Library schools (NOT to the pipeline); their history stays on their activity logs.`
                        )
                      ) {
                        deleteMutation.mutate(detail.id)
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Delete campaign
                  </Button>
                  </div>
                </div>

                {detail.schools.length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-[var(--color-text-muted)]">
                    Empty container &mdash; select schools in the Pipeline and use &ldquo;Move to campaign&rdquo;.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                          <th className="px-3 py-2">Name</th>
                          <th className="px-3 py-2">Level</th>
                          <th className="px-3 py-2">City</th>
                          <th className="px-3 py-2">Students</th>
                          <th className="px-3 py-2">Score</th>
                          <th className="px-3 py-2">Stage when moved</th>
                          <th className="px-3 py-2">Added</th>
                          <th className="px-3 py-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {detail.schools.map((school) => (
                          <tr
                            key={school.id}
                            className="cursor-pointer border-b border-[var(--color-border)] last:border-0 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                            onClick={() => setSelectedSchoolId(school.id)}
                          >
                            <td className="px-3 py-2 font-medium" title={school.name}>
                              {shortenSchoolName(school.name, school.city, school.name_disambiguator)}
                            </td>
                            <td className="px-3 py-2">{LEVEL_LABELS[school.level]}</td>
                            <td className="px-3 py-2">
                              <DataValueCell value={school.city} />
                            </td>
                            <td className="px-3 py-2">
                              <DataValueCell value={school.student_count} />
                            </td>
                            <td className="px-3 py-2">{school.score !== null ? `${school.score}/100` : "—"}</td>
                            <td className="px-3 py-2">
                              <StagePill stage={school.stage_at_move} />
                            </td>
                            <td className="px-3 py-2 text-[var(--color-text-muted)]">{formatDate(school.added_at)}</td>
                            <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                              <Button
                                size="sm"
                                variant="secondary"
                                disabled={returnMutation.isPending}
                                title="Put this school back into the pipeline, at the stage it had when it was moved here"
                                onClick={() => returnMutation.mutate(school.id)}
                              >
                                <Undo2 className="h-3.5 w-3.5" />
                                Return to pipeline
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {selectedSchoolId !== null && (
        <SchoolDetailDrawer schoolId={selectedSchoolId} onClose={() => setSelectedSchoolId(null)} />
      )}
    </div>
  )
}
