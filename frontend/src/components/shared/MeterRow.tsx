import { cn } from "@/lib/utils"

export function MeterRow({
  label,
  pct,
  valueLabel,
  colorClass,
  title,
  labelWidth = "w-40",
}: {
  label: string
  pct: number
  valueLabel: string
  colorClass?: string
  title?: string
  labelWidth?: string
}) {
  const clamped = Math.max(0, Math.min(100, pct))
  return (
    <div className="flex items-center gap-2 text-xs" title={title}>
      <span className={cn(labelWidth, "flex-shrink-0 text-[var(--color-text-muted)]")}>{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className={cn("h-full rounded-full", colorClass ?? "bg-[var(--color-accent)]")} style={{ width: `${clamped}%` }} />
      </div>
      <span className="w-28 flex-shrink-0 text-right font-medium">{valueLabel}</span>
    </div>
  )
}
