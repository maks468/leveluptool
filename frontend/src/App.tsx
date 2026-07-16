import { Navigate, Route, Routes } from "react-router-dom"
import { AppProviders } from "@/app/providers"
import { AppShell } from "@/app/AppShell"
import { DashboardPage } from "@/features/dashboard/DashboardPage"
import { LibraryPage } from "@/features/library/LibraryPage"
import { PipelinePage } from "@/features/pipeline/PipelinePage"
import { SchoolDetailPage } from "@/features/school-detail/SchoolDetailPage"
import { PriorityQueuePage } from "@/features/queue/PriorityQueuePage"
import { ReportsPage } from "@/features/reports/ReportsPage"

function App() {
  return (
    <AppProviders>
      <AppShell>
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/pipeline/board" element={<Navigate to="/pipeline" replace />} />
          <Route path="/pipeline/table" element={<Navigate to="/pipeline" replace />} />
          <Route path="/queue" element={<PriorityQueuePage />} />
          <Route path="/tasks" element={<Navigate to="/queue" replace />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/schools/:id" element={<SchoolDetailPage />} />
        </Routes>
      </AppShell>
    </AppProviders>
  )
}

export default App
