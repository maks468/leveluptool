import { useEffect, useState } from "react"
import { Button } from "@/components/ui/Button"

export function PaginationControls({
  page,
  pageSize,
  total,
  onPageChange,
  itemLabel = "results",
}: {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  itemLabel?: string
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const [inputValue, setInputValue] = useState(String(page))

  useEffect(() => setInputValue(String(page)), [page])

  function commitInput() {
    const parsed = Number(inputValue)
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= totalPages) {
      if (parsed !== page) onPageChange(parsed)
    } else {
      setInputValue(String(page))
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border)] px-3 py-2 text-sm">
      <span className="text-[var(--color-text-muted)]">
        Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total.toLocaleString()} {itemLabel}
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
          Previous
        </Button>
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)]">
          Page
          <input
            type="number"
            className="w-14 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-1.5 py-1 text-center text-xs"
            value={inputValue}
            min={1}
            max={totalPages}
            onChange={(e) => setInputValue(e.target.value)}
            onBlur={commitInput}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitInput()
            }}
          />
          of {totalPages.toLocaleString()}
        </span>
        <Button size="sm" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  )
}
