import { create } from "zustand"
import { persist } from "zustand/middleware"

export type PipelineColumnKey =
  | "city"
  | "director"
  | "teacher"
  | "website"
  | "best_email"
  | "stage"
  | "students"
  | "score"
  | "enrichment"
  | "next_follow_up"
  | "stage_updated"
  | "added_via"

export const PIPELINE_COLUMN_LABELS: Record<PipelineColumnKey, string> = {
  city: "City",
  director: "Director",
  teacher: "English teacher",
  website: "Website",
  best_email: "Best email",
  stage: "Stage",
  students: "Students",
  score: "Score",
  enrichment: "Enrichment",
  next_follow_up: "Next follow-up",
  stage_updated: "Stage updated",
  added_via: "Added via",
}

// Name (always first) and the Change-stage action (always last) are
// structural, not data columns, so they're never part of this managed set --
// hiding either would leave the table without an identifier or a way to act
// on a row at all.
const DEFAULT_ORDER: PipelineColumnKey[] = [
  "city",
  "director",
  "teacher",
  "website",
  "best_email",
  "stage",
  "students",
  "score",
  "enrichment",
  "next_follow_up",
  "stage_updated",
  "added_via",
]

export const DEFAULT_COLUMN_WIDTH = 160
export const DEFAULT_NAME_WIDTH = 260
export const MIN_COLUMN_WIDTH = 70

/** "name" is resizable like any other column but isn't part of the managed
 * set above -- it's always first and never hidden, so it isn't in
 * PipelineColumnKey, but it still needs a width slot. */
export type ResizableKey = PipelineColumnKey | "name"

interface PipelineColumnsState {
  order: PipelineColumnKey[]
  hidden: PipelineColumnKey[]
  widths: Partial<Record<ResizableKey, number>>
  toggleVisible: (key: PipelineColumnKey) => void
  /** Drops `dragged` into the position `target` currently occupies -- the
   * direct "grab a header and drop it where you want it" interaction,
   * replacing a separate up/down-per-click affordance. */
  reorder: (dragged: PipelineColumnKey, target: PipelineColumnKey) => void
  setWidth: (key: ResizableKey, px: number) => void
  reset: () => void
}

export const usePipelineColumns = create<PipelineColumnsState>()(
  persist(
    (set) => ({
      order: DEFAULT_ORDER,
      hidden: [],
      widths: {},
      toggleVisible: (key) =>
        set((s) => ({
          hidden: s.hidden.includes(key) ? s.hidden.filter((k) => k !== key) : [...s.hidden, key],
        })),
      reorder: (dragged, target) =>
        set((s) => {
          if (dragged === target) return s
          const withoutDragged = s.order.filter((k) => k !== dragged)
          const targetIdx = withoutDragged.indexOf(target)
          if (targetIdx === -1) return s
          const next = [...withoutDragged]
          next.splice(targetIdx, 0, dragged)
          return { order: next }
        }),
      setWidth: (key, px) =>
        set((s) => ({ widths: { ...s.widths, [key]: Math.max(MIN_COLUMN_WIDTH, px) } })),
      reset: () => set({ order: DEFAULT_ORDER, hidden: [], widths: {} }),
    }),
    { name: "levelup-pipeline-columns" }
  )
)
