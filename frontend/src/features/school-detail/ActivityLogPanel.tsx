import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { format } from "date-fns"
import { addActivityNote, getActivity } from "@/api/pipeline"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"
import { EnrichmentSourcesDisclosure } from "./EnrichmentSourcesDisclosure"

const ACTIVITY_LABEL: Record<string, string> = {
  note: "Note",
  stage_changed: "Stage changed",
  enrichment_completed: "Enrichment ran",
  ownership_subtype_confirmed: "Ownership confirmed",
  pulled_into_pipeline: "Pulled into pipeline",
  email_sent: "Email sent",
  email_opened: "Email opened",
  reminder_scheduled: "Reminder scheduled",
}

export function ActivityLogPanel({ schoolId }: { schoolId: number }) {
  const [note, setNote] = useState("")
  const queryClient = useQueryClient()

  const { data: entries = [] } = useQuery({
    queryKey: queryKeys.activity(schoolId),
    queryFn: () => getActivity(schoolId),
  })

  const addNote = useMutation({
    mutationFn: () => addActivityNote(schoolId, note),
    onSuccess: () => {
      setNote("")
      queryClient.invalidateQueries({ queryKey: queryKeys.activity(schoolId) })
    },
  })

  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">Activity log</h3>

      <div className="mb-3 flex gap-2">
        <textarea
          className="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          rows={2}
          placeholder="Log a call, email, or note&hellip;"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button
          variant="primary"
          size="sm"
          disabled={!note.trim() || addNote.isPending}
          onClick={() => addNote.mutate()}
        >
          Add
        </Button>
      </div>

      <div className="space-y-3">
        {entries.length === 0 && <p className="text-sm text-[var(--color-text-muted)]">No activity yet.</p>}
        {entries.map((entry) => (
          <div key={entry.id} className="border-l-2 border-[var(--color-border)] pl-3 text-sm">
            <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)]">
              <span>{ACTIVITY_LABEL[entry.activity_type] ?? entry.activity_type}</span>
              <span>{format(new Date(entry.occurred_at), "d MMM yyyy, HH:mm")}</span>
            </div>
            {entry.from_stage && entry.to_stage && (
              <p>
                {entry.from_stage} &rarr; {entry.to_stage}
              </p>
            )}
            {entry.note && <p>{entry.note}</p>}
            {entry.activity_type === "enrichment_completed" && (
              <EnrichmentSourcesDisclosure metadata={entry.metadata_json} />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
