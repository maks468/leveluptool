import { formatDistanceToNow } from "date-fns"
import { useNavigate } from "react-router-dom"
import type { RecentActivityEntry } from "@/types/domain"
import { shortenSchoolName } from "@/lib/schoolName"

const ACTIVITY_LABEL: Record<string, string> = {
  note: "Note added",
  stage_changed: "Stage changed",
  enrichment_completed: "Enrichment ran",
  ownership_subtype_confirmed: "Ownership confirmed",
  pulled_into_pipeline: "Pulled into pipeline",
  email_sent: "Email sent",
  email_opened: "Email opened",
  reminder_scheduled: "Reminder scheduled",
}

export function RecentActivityFeed({ entries }: { entries: RecentActivityEntry[] }) {
  const navigate = useNavigate()
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="mb-3 text-sm font-semibold">Recent activity</h2>
      {entries.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">No activity yet &mdash; pull some schools into the pipeline to get started.</p>
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => (
            <div key={entry.id} className="border-l-2 border-[var(--color-border)] pl-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  className="min-w-0 truncate font-medium hover:underline"
                  title={entry.school_name}
                  onClick={() => navigate(`/schools/${entry.school_id}`)}
                >
                  {shortenSchoolName(entry.school_name, entry.school_city)}
                </button>
                <span
                  className="flex-shrink-0 text-xs text-[var(--color-text-muted)]"
                  title={new Date(entry.occurred_at).toLocaleString()}
                >
                  {formatDistanceToNow(new Date(entry.occurred_at), { addSuffix: true })}
                </span>
              </div>
              <p className="text-xs text-[var(--color-text-muted)]">
                {ACTIVITY_LABEL[entry.activity_type] ?? entry.activity_type}
                {entry.from_stage && entry.to_stage && ` — ${entry.from_stage} → ${entry.to_stage}`}
              </p>
              {entry.note && <p className="text-xs">{entry.note}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
