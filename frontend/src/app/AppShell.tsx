import type { ReactNode } from "react"
import { NavLink } from "react-router-dom"
import { cn } from "@/lib/utils"
import { BatchJobTray } from "@/features/enrichment-jobs/BatchJobTray"
import { GlobalSearchBar } from "@/features/search/GlobalSearchBar"

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/library", label: "Library" },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/queue", label: "Priority queue" },
  { to: "/reports", label: "Reports" },
]

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-56 flex-shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="px-4 py-4">
          <span className="text-sm font-semibold tracking-tight">LevelUp Schools CRM</span>
        </div>
        <nav className="flex flex-col gap-1 px-3">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-[var(--color-accent)] text-[var(--color-accent-fg)]"
                    : "text-[var(--color-text-muted)] hover:bg-slate-100 dark:hover:bg-slate-800"
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center justify-end border-b border-[var(--color-border)] bg-[var(--color-surface)] px-6 py-2.5">
          <GlobalSearchBar />
        </header>
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto px-6 py-6">{children}</main>
      </div>
      <BatchJobTray />
    </div>
  )
}
