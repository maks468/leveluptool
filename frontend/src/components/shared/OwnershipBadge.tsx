import { CheckCircle2 } from "lucide-react"
import type { School } from "@/types/domain"
import { Badge } from "@/components/ui/Badge"

const SUBTYPE_LABEL: Record<string, string> = {
  niepubliczna: "Niepubliczna",
  spoleczna: "Społeczna",
  miedzynarodowa: "Międzynarodowa",
}

export function OwnershipBadge({ school }: { school: School }) {
  if (school.is_private === null) return <Badge variant="dashed">Ownership unknown</Badge>
  if (!school.is_private) return <Badge color="slate">Public</Badge>

  if (school.ownership_subtype && school.ownership_subtype_verified) {
    return (
      <Badge color="indigo">
        <CheckCircle2 className="h-3 w-3" />
        {SUBTYPE_LABEL[school.ownership_subtype]}
      </Badge>
    )
  }
  return <Badge variant="dashed">Private &middot; subtype unverified</Badge>
}
