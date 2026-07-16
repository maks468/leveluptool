import { useState } from "react"
import { Columns3 } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { PipelinePanel } from "./components/PipelinePanel"

let nextPanelId = 1

/** Multiple independent panels side by side -- each is a fully separate
 * PipelinePanel with its own filters/sort/selection, so one can show
 * "Not contacted, Warsaw" while another shows a saved view for a
 * different region, without either affecting the other. Always at least
 * one panel; the close button only appears once there's more than one. */
export function PipelinePage() {
  const [panelIds, setPanelIds] = useState<number[]>(() => [nextPanelId++])

  function addPanel() {
    setPanelIds((ids) => [...ids, nextPanelId++])
  }

  function removePanel(id: number) {
    setPanelIds((ids) => (ids.length > 1 ? ids.filter((x) => x !== id) : ids))
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-shrink-0 items-center justify-between">
        <h1 className="text-lg font-semibold">Pipeline</h1>
        <Button size="sm" onClick={addPanel}>
          <Columns3 className="h-4 w-4" />
          Add panel
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 items-stretch gap-4 overflow-x-auto pb-2">
        {panelIds.map((id, i) => (
          <div key={id} className="flex min-h-0 min-w-[640px] flex-1 flex-col">
            <PipelinePanel
              onClose={panelIds.length > 1 ? () => removePanel(id) : undefined}
              panelLabel={`Panel ${i + 1}`}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
