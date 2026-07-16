import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet"
import "leaflet/dist/leaflet.css"
import { Map as MapIcon } from "lucide-react"
import { getMapSchools } from "@/api/pipeline"
import { queryKeys } from "@/api/queryKeys"
import type { MapSchool } from "@/types/domain"
import { STAGE_LABELS } from "@/types/domain"
import { scoreHue } from "@/lib/scoreColor"
import { shortenSchoolName } from "@/lib/schoolName"
import { SchoolDetailDrawer } from "@/features/school-detail/SchoolDetailDrawer"

const POLAND_CENTER: [number, number] = [52.0, 19.5]

function markerColor(score: number | null): string {
  if (score === null) return "hsl(220 9% 55%)"
  return `hsl(${scoreHue(score)} 68% 40%)`
}

function formatLastContact(iso: string | null): string {
  if (!iso) return "No activity logged yet"
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return "Today"
  if (days === 1) return "1 day ago"
  return `${days} days ago`
}

function MapPopup({ school, onOpen }: { school: MapSchool; onOpen: (id: number) => void }) {
  const contact = [school.director_name, school.english_teacher_name].filter(Boolean).join(" · ")
  return (
    <div className="min-w-48 space-y-1 text-sm">
      <div className="font-semibold">{shortenSchoolName(school.name, school.city)}</div>
      <div className="text-xs text-[var(--color-text-muted)]">
        {school.city ?? "—"} · {STAGE_LABELS[school.stage]} · {school.score !== null ? `${school.score}/100` : "Not scored"}
      </div>
      <div className="text-xs">
        <span className="text-[var(--color-text-muted)]">Contact: </span>
        {contact || "Not yet found"}
      </div>
      <div className="text-xs">
        <span className="text-[var(--color-text-muted)]">Last contact: </span>
        {formatLastContact(school.last_activity_at)}
      </div>
      {school.last_note && <div className="text-xs italic text-[var(--color-text-muted)]">&ldquo;{school.last_note}&rdquo;</div>}
      <button
        type="button"
        className="pt-1 text-xs font-medium text-[var(--color-accent)] hover:underline"
        onClick={() => onOpen(school.id)}
      >
        View full details &rarr;
      </button>
    </div>
  )
}

export function PipelineMapCard() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const { data: schools = [], isLoading } = useQuery({
    queryKey: queryKeys.pipelineMap(),
    queryFn: getMapSchools,
  })

  const plottable = schools.filter((s) => s.latitude !== null && s.longitude !== null)

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <div className="mb-3 flex items-center gap-2">
        <MapIcon className="h-4 w-4 text-[var(--color-text-muted)]" />
        <h2 className="text-sm font-semibold">Pipeline map</h2>
        <span className="text-xs text-[var(--color-text-muted)]">
          {plottable.length} school{plottable.length === 1 ? "" : "s"} plotted · color = score
        </span>
      </div>

      {isLoading && <div className="py-10 text-center text-sm text-[var(--color-text-muted)]">Loading&hellip;</div>}

      {!isLoading && plottable.length === 0 && (
        <div className="py-10 text-center text-sm text-[var(--color-text-muted)]">
          No pipeline schools with a known location yet &mdash; pull some schools into the pipeline to see them here.
        </div>
      )}

      {!isLoading && plottable.length > 0 && (
        <MapContainer
          bounds={plottable.map((s) => [s.latitude, s.longitude] as [number, number])}
          boundsOptions={{ padding: [30, 30] }}
          center={POLAND_CENTER}
          zoom={6}
          scrollWheelZoom={false}
          style={{ height: 420, width: "100%" }}
          className="overflow-hidden rounded-md"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {plottable.map((school) => (
            <CircleMarker
              key={school.id}
              center={[school.latitude, school.longitude]}
              radius={7}
              pathOptions={{ color: markerColor(school.score), fillColor: markerColor(school.score), fillOpacity: 0.85, weight: 1 }}
            >
              <Popup>
                <MapPopup school={school} onOpen={setSelectedId} />
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      )}

      {selectedId !== null && <SchoolDetailDrawer schoolId={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}
