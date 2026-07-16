import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { X } from "lucide-react"
import { addSchoolTag, createTag, getSchoolTags, listTags, removeSchoolTag } from "@/api/crm"
import { queryKeys } from "@/api/queryKeys"
import { Badge, type BadgeColor } from "@/components/ui/Badge"
import type { Tag as TagType } from "@/types/domain"

/** Free-form, multi-select labels independent of pipeline stage -- for
 * nuance that doesn't fit the linear stage model ("has EU funding",
 * "revisit next spring", "gatekeeper is hostile"). */
export function TagsPanel({ schoolId }: { schoolId: number }) {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [newTagName, setNewTagName] = useState("")

  const { data: schoolTags = [] } = useQuery({
    queryKey: queryKeys.schoolTags(schoolId),
    queryFn: () => getSchoolTags(schoolId),
  })
  const { data: allTags = [] } = useQuery({ queryKey: queryKeys.tags(), queryFn: listTags })

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: queryKeys.schoolTags(schoolId) })
    queryClient.invalidateQueries({ queryKey: queryKeys.tags() })
  }

  const addMutation = useMutation({
    mutationFn: (tagId: number) => addSchoolTag(schoolId, tagId),
    onSuccess: invalidate,
  })
  const removeMutation = useMutation({
    mutationFn: (tagId: number) => removeSchoolTag(schoolId, tagId),
    onSuccess: invalidate,
  })
  const createMutation = useMutation({
    mutationFn: (name: string) => createTag(name, "slate"),
    onSuccess: (tag) => {
      invalidate()
      addMutation.mutate(tag.id)
      setNewTagName("")
      setAdding(false)
    },
  })

  const availableTags = allTags.filter((t) => !schoolTags.some((st) => st.id === t.id))

  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-[var(--color-text-muted)]">Tags</label>
      <div className="flex flex-wrap items-center gap-1.5">
        {schoolTags.map((tag: TagType) => (
          <Badge key={tag.id} color={tag.color as BadgeColor}>
            {tag.name}
            <button type="button" onClick={() => removeMutation.mutate(tag.id)}>
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="rounded-full border border-dashed border-[var(--color-border)] px-2 py-0.5 text-xs text-[var(--color-text-muted)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
          >
            + Tag
          </button>
        )}
        {adding && (
          <div className="flex items-center gap-1">
            {availableTags.length > 0 && (
              <select
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-0.5 text-xs"
                onChange={(e) => {
                  if (e.target.value) {
                    addMutation.mutate(Number(e.target.value))
                    setAdding(false)
                  }
                }}
                defaultValue=""
              >
                <option value="" disabled>
                  Pick existing&hellip;
                </option>
                {availableTags.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            )}
            <input
              type="text"
              placeholder="New tag name"
              autoFocus
              className="w-28 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-0.5 text-xs"
              value={newTagName}
              onChange={(e) => setNewTagName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTagName.trim()) createMutation.mutate(newTagName.trim())
                if (e.key === "Escape") setAdding(false)
              }}
              onBlur={() => {
                if (!newTagName.trim()) setAdding(false)
              }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
