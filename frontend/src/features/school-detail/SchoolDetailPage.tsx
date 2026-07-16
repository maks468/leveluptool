import { useNavigate, useParams } from "react-router-dom"
import { SchoolDetailDrawer } from "./SchoolDetailDrawer"

/** A stable, linkable URL for one school -- used by Global Search results
 * (previously there was no way to deep-link to a school at all, only open
 * its drawer by clicking a row already visible in a filtered table). */
export function SchoolDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const schoolId = Number(id)

  if (!schoolId) return null
  return <SchoolDetailDrawer schoolId={schoolId} onClose={() => navigate("/library")} />
}
