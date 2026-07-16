import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ArrowRightCircle } from "lucide-react"
import type { School } from "@/types/domain"
import { ScoreBadge } from "@/components/shared/ScoreBadge"
import { DataValueCell } from "@/components/shared/DataValueCell"
import { Button } from "@/components/ui/Button"
import { pullIntoPipeline } from "@/api/pipeline"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"
import { shortenSchoolName } from "@/lib/schoolName"

export function TopLeadsList({ schools }: { schools: School[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const pullOne = useMutation({
    mutationFn: (schoolId: number) => pullIntoPipeline({ schoolIds: [schoolId] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard-summary"] })
      queryClient.invalidateQueries({ queryKey: ["dashboard-top-leads"] })
    },
  })

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="mb-3 text-sm font-semibold">Top-scored leads not yet contacted</h2>
      {schools.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">No unscored gap here &mdash; every high scorer is already in the pipeline.</p>
      ) : (
        <div className="space-y-1">
          {schools.map((school) => (
            <div
              key={school.id}
              className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50"
            >
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left text-sm font-medium hover:underline"
                onClick={() => setSelectedId(school.id)}
                title={school.name}
              >
                {shortenSchoolName(school.name, school.city)}
              </button>
              <span className="flex-shrink-0 text-xs text-[var(--color-text-muted)]">
                <DataValueCell value={school.city} />
              </span>
              <ScoreBadge score={school.score} />
              <Button
                size="sm"
                disabled={pullOne.isPending}
                onClick={() => pullOne.mutate(school.id)}
                title="Pull into pipeline"
              >
                <ArrowRightCircle className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>
      )}
      {selectedId !== null && <SchoolDetailDrawer schoolId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
