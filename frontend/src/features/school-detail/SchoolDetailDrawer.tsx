import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { getSchool } from "@/api/schools"
import { setStage } from "@/api/pipeline"
import { queryKeys } from "@/api/queryKeys"
import { Drawer } from "@/components/ui/Dialog"
import { Badge } from "@/components/ui/Badge"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { OwnershipBadge } from "@/components/shared/OwnershipBadge"
import { ScoreBadge } from "@/components/shared/ScoreBadge"
import { LEVEL_LABELS, PIPELINE_STAGES, STAGE_LABELS } from "@/types/domain"
import type { PipelineStage } from "@/types/domain"
import { ActivityLogPanel } from "./ActivityLogPanel"
import { EnrichmentPanel } from "./EnrichmentPanel"
import { FollowUpPanel } from "./FollowUpPanel"
import { TagsPanel } from "./TagsPanel"

export function SchoolDetailDrawer({ schoolId, onClose }: { schoolId: number; onClose: () => void }) {
  const queryClient = useQueryClient()

  const { data: school } = useQuery({
    queryKey: queryKeys.school(schoolId),
    queryFn: () => getSchool(schoolId),
  })

  const stageMutation = useMutation({
    mutationFn: (stage: PipelineStage) => setStage(schoolId, stage),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.school(schoolId) })
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: queryKeys.activity(schoolId) })
    },
  })

  if (!school) return null

  return (
    <Drawer open onOpenChange={(open) => !open && onClose()} title={school.name}>
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <OwnershipBadge school={school} />
          <ScoreBadge score={school.score} />
          {school.is_adult_education && <Badge color="amber">Adult education</Badge>}
        </div>

        {school.in_pipeline && school.stage && (
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Pipeline stage</label>
            <select
              className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
              value={school.stage}
              onChange={(e) => stageMutation.mutate(e.target.value as PipelineStage)}
            >
              {PIPELINE_STAGES.map((s) => (
                <option key={s} value={s}>
                  {STAGE_LABELS[s]}
                </option>
              ))}
            </select>
          </div>
        )}

        {school.in_pipeline && (
          <FollowUpPanel
            schoolId={schoolId}
            nextActionNote={school.next_action_note}
            nextActionDate={school.next_action_date}
          />
        )}

        <TagsPanel schoolId={schoolId} />

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
          <dt className="text-[var(--color-text-muted)]">RSPO ID</dt>
          <dd>{school.rspo_id}</dd>
          <dt className="text-[var(--color-text-muted)]">Level</dt>
          <dd>{LEVEL_LABELS[school.level]}</dd>
          <dt className="text-[var(--color-text-muted)]">City</dt>
          <dd>
            <DataValueCell value={school.city} /> <DataValueCell value={school.voivodeship} />
          </dd>
          <dt className="text-[var(--color-text-muted)]">Students</dt>
          <dd>
            <DataValueCell value={school.student_count} />
          </dd>
          <dt className="text-[var(--color-text-muted)]">School profile</dt>
          <dd>
            <DataValueCell value={school.school_profile} />
          </dd>
        </dl>

        {school.score && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">Score breakdown</h3>
            <table className="w-full text-xs">
              <tbody>
                {Object.entries(school.score.criterion_breakdown).map(([key, c]) => (
                  <tr key={key} className="border-b border-[var(--color-border)] last:border-0">
                    <td className="py-1 capitalize">{key.replace(/_/g, " ")}</td>
                    <td className="py-1 text-right">
                      {c.points}/{c.max}
                    </td>
                    <td className="py-1 pl-2 text-right text-[var(--color-text-muted)]">{c.basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <EnrichmentPanel school={school} />
        <ActivityLogPanel schoolId={schoolId} />
      </div>
    </Drawer>
  )
}
