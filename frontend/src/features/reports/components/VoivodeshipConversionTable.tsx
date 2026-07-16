import { useQuery } from "@tanstack/react-query"
import { getFunnelReport } from "@/api/reports"
import { queryKeys } from "@/api/queryKeys"

export function VoivodeshipConversionTable() {
  const { data } = useQuery({ queryKey: queryKeys.funnelReport(), queryFn: getFunnelReport })
  const rows = data?.voivodeship_conversion ?? []

  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="mb-1 text-sm font-semibold">Conversion by voivodeship</h2>
      <p className="mb-3 text-xs text-[var(--color-text-muted)]">Which regions convert best, ranked by pipeline size.</p>
      {rows.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">No pipeline schools yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
                <th className="px-2 py-1.5">Voivodeship</th>
                <th className="px-2 py-1.5 text-right">In pipeline</th>
                <th className="px-2 py-1.5 text-right">Won</th>
                <th className="px-2 py-1.5 text-right">Lost</th>
                <th className="px-2 py-1.5 text-right">Win rate</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={r.voivodeship}
                  className={i % 2 === 1 ? "bg-slate-50/60 dark:bg-slate-900/30" : undefined}
                >
                  <td className="px-2 py-1.5 font-medium">{r.voivodeship}</td>
                  <td className="px-2 py-1.5 text-right">{r.total}</td>
                  <td className="px-2 py-1.5 text-right text-green-700 dark:text-green-400">{r.won}</td>
                  <td className="px-2 py-1.5 text-right text-red-700 dark:text-red-400">{r.lost}</td>
                  <td className="px-2 py-1.5 text-right">{r.win_rate !== null ? `${Math.round(r.win_rate * 100)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
