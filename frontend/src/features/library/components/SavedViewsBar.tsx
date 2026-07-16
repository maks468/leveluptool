import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Star, Trash2 } from "lucide-react"
import { createSavedView, deleteSavedView, listSavedViews, toggleSavedViewFavorite } from "@/api/crm"
import { queryKeys } from "@/api/queryKeys"
import { useLibraryFilters } from "../useLibraryFilters"
import type { LibraryFilters } from "@/types/domain"
import { cn } from "@/lib/utils"

export function SavedViewsBar() {
  const { filters, sort, resultLimit, applyView } = useLibraryFilters()
  const [activeId, setActiveId] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const { data: views = [] } = useQuery({ queryKey: queryKeys.savedViews("library"), queryFn: () => listSavedViews("library") })

  const saveMutation = useMutation({
    mutationFn: (name: string) =>
      createSavedView({ name, scope: "library", filters_json: filters, sort, result_limit: resultLimit }),
    onSuccess: (view) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.savedViews("library") })
      setActiveId(view.id)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSavedView,
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.savedViews("library") })
      if (activeId === id) setActiveId(null)
    },
  })

  const favoriteMutation = useMutation({
    mutationFn: toggleSavedViewFavorite,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.savedViews("library") }),
  })

  function handleSave() {
    const name = window.prompt("Name this view (e.g. \"Mazowieckie private primaries, not yet contacted\")")
    if (name && name.trim()) saveMutation.mutate(name.trim())
  }

  function handleApply(viewId: number) {
    const view = views.find((v) => v.id === viewId)
    if (!view) return
    setActiveId(view.id)
    applyView(view.filters_json as unknown as LibraryFilters, view.sort, view.result_limit)
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2">
      <span className="mr-1 text-xs font-medium text-[var(--color-text-muted)]">Views</span>
      {views.length === 0 && <span className="text-xs text-[var(--color-text-muted)]">No saved views yet</span>}
      {views.map((view) => (
        <div
          key={view.id}
          className={cn(
            "group flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs",
            activeId === view.id
              ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10 text-[var(--color-accent)]"
              : "border-[var(--color-border)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
          )}
        >
          <button type="button" onClick={() => handleApply(view.id)} className="font-medium">
            {view.name}
          </button>
          <button
            type="button"
            title={view.is_favorite ? "Unfavorite" : "Favorite"}
            onClick={() => favoriteMutation.mutate(view.id)}
          >
            <Star className={cn("h-3 w-3", view.is_favorite && "fill-amber-400 text-amber-400")} />
          </button>
          <button
            type="button"
            title="Delete view"
            className="opacity-0 group-hover:opacity-100"
            onClick={() => {
              if (window.confirm(`Delete the saved view "${view.name}"?`)) deleteMutation.mutate(view.id)
            }}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={handleSave}
        className="ml-1 rounded-full border border-dashed border-[var(--color-border)] px-2.5 py-1 text-xs text-[var(--color-text-muted)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
      >
        + Save current view
      </button>
    </div>
  )
}
