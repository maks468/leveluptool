import { QualificationFiltersPanel } from "./components/QualificationFiltersPanel"
import { PreviewAndPullBar } from "./components/PreviewAndPullBar"
import { LibraryResultsTable } from "./components/LibraryResultsTable"
import { SavedViewsBar } from "./components/SavedViewsBar"

export function LibraryPage() {
  return (
    <div className="grid grid-cols-[280px_1fr] gap-4">
      <div>
        <QualificationFiltersPanel />
      </div>
      <div className="space-y-4">
        <h1 className="text-lg font-semibold">Library</h1>
        <SavedViewsBar />
        <PreviewAndPullBar />
        <LibraryResultsTable />
      </div>
    </div>
  )
}
