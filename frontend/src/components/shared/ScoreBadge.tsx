import type { CSSProperties } from "react"
import type { Score } from "@/types/domain"
import { scoreHue } from "@/lib/scoreColor"
import { MissingDataBadge } from "./MissingDataBadge"

export function ScoreBadge({ score }: { score: Score | null }) {
  if (!score || score.total_score === null) {
    return <MissingDataBadge label="Not scored" />
  }
  const hue = scoreHue(score.total_score)
  return (
    <span
      className="score-badge inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap"
      style={{ "--score-hue": hue } as CSSProperties}
      title={`${score.rubric_type} rubric v${score.rubric_version}`}
    >
      <span className="score-dot h-1.5 w-1.5 rounded-full" />
      {score.total_score}/100
    </span>
  )
}
