import { useState } from "react"
import { SlidersHorizontal, RotateCcw } from "lucide-react"
import { ConfirmDialog } from "@/components/ui/Dialog"
import { Button } from "@/components/ui/Button"
import { usePipelineColumns, PIPELINE_COLUMN_LABELS } from "../usePipelineColumns"

/** Which optional columns show. Reordering and resizing now happen
 * directly on the table's own headers (drag a header to move it, drag its
 * right edge to resize) -- this dialog is only for show/hide, since a
 * hidden column has no header left in the table to grab back into view. */
export function PipelineColumnManager() {
  const [open, setOpen] = useState(false)
  const { order, hidden, toggleVisible, reset } = usePipelineColumns()

  return (
    <>
      <Button className="flex-shrink-0" onClick={() => setOpen(true)} title="Choose which columns show">
        <SlidersHorizontal className="h-4 w-4" />
        Columns
      </Button>

      <ConfirmDialog open={open} onOpenChange={setOpen} title="Show/hide columns">
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">
          Drag a column header to reorder it, or drag its right edge to resize.
        </p>
        <div className="space-y-1">
          {order.map((key) => {
            const isHidden = hidden.includes(key)
            return (
              <label
                key={key}
                className="flex items-center gap-2 rounded-md border border-[var(--color-border)] px-2.5 py-1.5 text-sm"
              >
                <input type="checkbox" checked={!isHidden} onChange={() => toggleVisible(key)} />
                <span className={isHidden ? "text-[var(--color-text-muted)]" : undefined}>
                  {PIPELINE_COLUMN_LABELS[key]}
                </span>
              </label>
            )
          })}
        </div>

        <button
          type="button"
          onClick={reset}
          className="mt-3 flex items-center gap-1.5 text-xs text-[var(--color-accent)] hover:underline"
        >
          <RotateCcw className="h-3 w-3" />
          Reset to default
        </button>
      </ConfirmDialog>
    </>
  )
}
