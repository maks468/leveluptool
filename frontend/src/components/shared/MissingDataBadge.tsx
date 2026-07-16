import { CircleDashed } from "lucide-react"
import { Badge } from "@/components/ui/Badge"

export function MissingDataBadge({ label = "Missing" }: { label?: string }) {
  return (
    <Badge variant="dashed">
      <CircleDashed className="h-3 w-3" />
      {label}
    </Badge>
  )
}
