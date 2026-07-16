import { create } from "zustand"
import type { LibraryFilters, OwnershipSubtype } from "@/types/domain"
import { DEFAULT_LIBRARY_FILTERS } from "@/types/domain"

const DEFAULT_SORT = "score:desc"

interface LibraryFiltersState {
  filters: LibraryFilters
  sort: string
  resultLimit: number | null
  previewedCount: number | null
  set: <K extends keyof LibraryFilters>(key: K, value: LibraryFilters[K]) => void
  toggleOwnershipSubtype: (subtype: OwnershipSubtype) => void
  setPreviewedCount: (count: number | null) => void
  setSort: (sort: string) => void
  setResultLimit: (limit: number | null) => void
  /** Loads a saved view's filters+sort+limit all at once (e.g. clicking a
   * saved view), as opposed to `set`, which is for one filter field at a time. */
  applyView: (filters: LibraryFilters, sort: string | null, resultLimit: number | null) => void
  reset: () => void
}

export const useLibraryFilters = create<LibraryFiltersState>((set, get) => ({
  filters: DEFAULT_LIBRARY_FILTERS,
  sort: DEFAULT_SORT,
  resultLimit: null,
  previewedCount: null,
  set: (key, value) =>
    set((state) => ({
      filters: { ...state.filters, [key]: value },
      previewedCount: null, // any filter change invalidates the last preview
    })),
  toggleOwnershipSubtype: (subtype) => {
    const current = get().filters.ownership_subtype
    const next = current.includes(subtype) ? current.filter((s) => s !== subtype) : [...current, subtype]
    set((state) => ({ filters: { ...state.filters, ownership_subtype: next }, previewedCount: null }))
  },
  setPreviewedCount: (count) => set({ previewedCount: count }),
  setSort: (sort) => set({ sort }),
  setResultLimit: (resultLimit) => set({ resultLimit }),
  applyView: (filters, sort, resultLimit) =>
    set({ filters, sort: sort ?? DEFAULT_SORT, resultLimit, previewedCount: null }),
  reset: () => set({ filters: DEFAULT_LIBRARY_FILTERS, sort: DEFAULT_SORT, resultLimit: null, previewedCount: null }),
}))
