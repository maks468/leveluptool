import type { ReactNode } from "react"

export function StatCard({
  label,
  value,
  sublabel,
  icon,
}: {
  label: string
  value: string | number
  sublabel?: string
  icon?: ReactNode
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--color-text-muted)]">{label}</span>
        {icon && <span className="text-[var(--color-text-muted)]">{icon}</span>}
      </div>
      <div className="mt-1 text-2xl font-semibold">{typeof value === "number" ? value.toLocaleString() : value}</div>
      {sublabel && <div className="mt-0.5 text-xs text-[var(--color-text-muted)]">{sublabel}</div>}
    </div>
  )
}
