import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Search } from "lucide-react"
import { searchSchools } from "@/api/crm"
import { queryKeys } from "@/api/queryKeys"
import { LEVEL_LABELS } from "@/types/domain"

/** With 25k+ records, there was previously no way to just type a school's
 * name and jump to it -- only structured dropdown filters. */
export function GlobalSearchBar() {
  const [q, setQ] = useState("")
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const containerRef = useRef<HTMLDivElement>(null)

  const { data: results = [], isFetching } = useQuery({
    queryKey: queryKeys.search(q),
    queryFn: () => searchSchools(q),
    enabled: q.trim().length >= 2,
  })

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [])

  function goTo(id: number) {
    setOpen(false)
    setQ("")
    navigate(`/schools/${id}`)
  }

  const showDropdown = open && q.trim().length >= 2

  return (
    <div ref={containerRef} className="relative w-80">
      <div className="flex items-center gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5">
        <Search className="h-4 w-4 flex-shrink-0 text-[var(--color-text-muted)]" />
        <input
          type="text"
          placeholder="Search schools by name or city..."
          className="w-full bg-transparent text-sm outline-none"
          value={q}
          onChange={(e) => {
            setQ(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
        />
      </div>
      {showDropdown && (
        <div className="absolute z-20 mt-1 max-h-96 w-full overflow-y-auto rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] shadow-lg">
          {isFetching && <div className="px-3 py-2 text-xs text-[var(--color-text-muted)]">Searching&hellip;</div>}
          {!isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-[var(--color-text-muted)]">No schools match &ldquo;{q}&rdquo;</div>
          )}
          {results.map((r) => (
            <button
              key={r.id}
              type="button"
              onClick={() => goTo(r.id)}
              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <span className="min-w-0 flex-1 truncate">
                <span className="font-medium">{r.name}</span>
                <span className="ml-1.5 text-xs text-[var(--color-text-muted)]">
                  {r.city ?? "?"} &middot; {LEVEL_LABELS[r.level]}
                  {r.in_pipeline && " · in pipeline"}
                </span>
              </span>
              {r.score !== null && (
                <span className="flex-shrink-0 text-xs text-[var(--color-text-muted)]">{r.score}/100</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
