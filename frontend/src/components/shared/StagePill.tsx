import type { PipelineStage } from "@/types/domain"
import { STAGE_LABELS } from "@/types/domain"
import { Badge } from "@/components/ui/Badge"

const STAGE_COLOR: Record<PipelineStage, "slate" | "blue" | "cyan" | "violet" | "purple" | "amber" | "green" | "red"> = {
  not_contacted: "slate",
  contacted: "blue",
  responded: "cyan",
  meeting_booked: "violet",
  meeting_held: "purple",
  next_step_agreed: "amber",
  won: "green",
  lost: "red",
}

export function StagePill({ stage }: { stage: PipelineStage }) {
  return <Badge color={STAGE_COLOR[stage]}>{STAGE_LABELS[stage]}</Badge>
}
