import type { OwnershipSubtype } from "@/types/domain"
import { useLibraryFilters } from "../useLibraryFilters"

const SUBTYPES: { key: OwnershipSubtype; label: string }[] = [
  { key: "niepubliczna", label: "Niepubliczna" },
  { key: "spoleczna", label: "Społeczna" },
  { key: "miedzynarodowa", label: "Międzynarodowa" },
]

export function OwnershipFilter() {
  const { filters, set, toggleOwnershipSubtype } = useLibraryFilters()

  const allChecked = filters.ownership_subtype.length === SUBTYPES.length

  function toggleAllPrivateChildren() {
    set("ownership_subtype", allChecked ? [] : SUBTYPES.map((s) => s.key))
  }

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-[var(--color-text-muted)]">Ownership</label>
      <p className="text-xs text-[var(--color-text-muted)]">Check both to see everything &mdash; no need to pick just one.</p>

      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          checked={filters.ownership_public}
          onChange={(e) => set("ownership_public", e.target.checked)}
        />
        Public
      </label>
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          type="checkbox"
          checked={filters.ownership_private}
          onChange={(e) => set("ownership_private", e.target.checked)}
        />
        Private
      </label>

      {filters.ownership_private && (
        <div className="ml-6 space-y-1.5 border-l border-[var(--color-border)] pl-3">
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={allChecked} onChange={toggleAllPrivateChildren} />
            <span className="font-medium">All / none</span>
          </label>
          {SUBTYPES.map((s) => (
            <label key={s.key} className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={filters.ownership_subtype.includes(s.key)}
                onChange={() => toggleOwnershipSubtype(s.key)}
              />
              {s.label}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
