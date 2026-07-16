import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { setFollowUp } from "@/api/pipeline"
import { queryKeys } from "@/api/queryKeys"
import { Button } from "@/components/ui/Button"

/** Sets the follow-up date/note that the Tasks Due list reads -- without
 * this, next_action_date/note had no editing UI anywhere in the app. */
export function FollowUpPanel({
  schoolId,
  nextActionNote,
  nextActionDate,
}: {
  schoolId: number
  nextActionNote: string | null
  nextActionDate: string | null
}) {
  const queryClient = useQueryClient()
  const [note, setNote] = useState(nextActionNote ?? "")
  const [date, setDate] = useState(nextActionDate ? nextActionDate.slice(0, 10) : "")

  const mutation = useMutation({
    mutationFn: () =>
      setFollowUp(schoolId, {
        next_action_note: note.trim() || null,
        next_action_date: date ? new Date(`${date}T00:00:00`).toISOString() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.school(schoolId) })
      queryClient.invalidateQueries({ queryKey: ["tasks-due"] })
    },
  })

  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Follow-up</label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="date"
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
        <input
          type="text"
          placeholder='Note (e.g. "call about pilot")'
          className="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button size="sm" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          Save
        </Button>
      </div>
    </div>
  )
}
