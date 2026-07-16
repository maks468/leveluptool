import { FunnelSection } from "./components/FunnelSection"
import { VoivodeshipConversionTable } from "./components/VoivodeshipConversionTable"
import { DataQualitySection } from "./components/DataQualitySection"

export function ReportsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold">Reports</h1>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--color-text-muted)]">Conversion &amp; funnel</h2>
        <FunnelSection />
        <VoivodeshipConversionTable />
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--color-text-muted)]">Data quality</h2>
        <DataQualitySection />
      </section>
    </div>
  )
}
