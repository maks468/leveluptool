import type { HTMLAttributes, ReactNode } from "react"
import { cn } from "@/lib/utils"

type BadgeVariant = "solid" | "muted" | "dashed"
export type BadgeColor = "slate" | "indigo" | "green" | "red" | "amber" | "cyan" | "violet" | "blue" | "purple"

export function Badge({
  children,
  variant = "solid",
  color = "slate",
  className,
  ...rest
}: {
  children: ReactNode
  variant?: BadgeVariant
  color?: BadgeColor
  className?: string
} & HTMLAttributes<HTMLSpanElement>) {
  const colorClasses: Record<string, string> = {
    slate: "bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600",
    indigo: "bg-indigo-100 text-indigo-700 border-indigo-300 dark:bg-indigo-900/40 dark:text-indigo-300 dark:border-indigo-700",
    green: "bg-green-100 text-green-700 border-green-300 dark:bg-green-900/40 dark:text-green-300 dark:border-green-700",
    red: "bg-red-100 text-red-700 border-red-300 dark:bg-red-900/40 dark:text-red-300 dark:border-red-700",
    amber: "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-700",
    cyan: "bg-cyan-100 text-cyan-700 border-cyan-300 dark:bg-cyan-900/40 dark:text-cyan-300 dark:border-cyan-700",
    violet: "bg-violet-100 text-violet-700 border-violet-300 dark:bg-violet-900/40 dark:text-violet-300 dark:border-violet-700",
    blue: "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/40 dark:text-blue-300 dark:border-blue-700",
    purple: "bg-purple-100 text-purple-700 border-purple-300 dark:bg-purple-900/40 dark:text-purple-300 dark:border-purple-700",
  }

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        variant === "solid" && colorClasses[color],
        variant === "muted" && "bg-transparent text-[var(--color-text-muted)] border-[var(--color-border)]",
        variant === "dashed" && "bg-transparent text-[var(--color-text-muted)] border-dashed border-[var(--color-border)]",
        className
      )}
      {...rest}
    >
      {children}
    </span>
  )
}
