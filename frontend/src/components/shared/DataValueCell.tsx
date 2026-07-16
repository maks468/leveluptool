import type { ReactNode } from "react"
import { MissingDataBadge } from "./MissingDataBadge"

/** The single place that decides "unknown" vs. a real value -- every
 * column renderer should go through this rather than special-casing
 * null/blank itself. */
export function DataValueCell({
  value,
  missingLabel = "Missing",
  children,
}: {
  value: unknown
  missingLabel?: string
  children?: ReactNode
}) {
  const isMissing = value === null || value === undefined || value === ""
  if (isMissing) return <MissingDataBadge label={missingLabel} />
  return <>{children ?? String(value)}</>
}
