import { create } from "zustand"

interface LibrarySelectionState {
  selectedIds: Set<number>
  toggle: (id: number) => void
  setMany: (ids: number[], selected: boolean) => void
  clear: () => void
}

export const useLibrarySelection = create<LibrarySelectionState>((set, get) => ({
  selectedIds: new Set(),
  toggle: (id) => {
    const next = new Set(get().selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    set({ selectedIds: next })
  },
  setMany: (ids, selected) => {
    const next = new Set(get().selectedIds)
    for (const id of ids) {
      if (selected) next.add(id)
      else next.delete(id)
    }
    set({ selectedIds: next })
  },
  clear: () => set({ selectedIds: new Set() }),
}))
