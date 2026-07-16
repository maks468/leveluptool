import type { EnrichmentSource } from "@/types/domain"

const STATUS_LABEL: Record<EnrichmentSource["status"], string> = {
  ok: "Checked",
  unreachable: "Unreachable",
  search_returned_no_results: "No results",
}

/** Renders the full trail of what an enrichment run actually looked at --
 * every URL it fetched (own site or found via search) and every search
 * query it ran, successful or not. Nothing here is invented; this is
 * exactly what's stored on the activity log entry. */
export function EnrichmentSourcesDisclosure({ metadata }: { metadata: Record<string, unknown> }) {
  const sources = (metadata.sources_checked as EnrichmentSource[] | undefined) ?? []
  if (sources.length === 0) return null

  const foundDirector = Boolean(metadata.found_director_name)
  const foundEnglishTeacher = Boolean(metadata.found_english_teacher_name)
  const foundEmail = Boolean(metadata.found_email)

  return (
    <details className="mt-1.5 text-xs">
      <summary className="cursor-pointer select-none text-[var(--color-text-muted)] hover:text-[var(--color-text)]">
        {sources.length} source{sources.length === 1 ? "" : "s"} checked &middot; director{" "}
        {foundDirector ? "✓" : "✗"} &middot; English teacher {foundEnglishTeacher ? "✓" : "✗"} &middot;
        email {foundEmail ? "✓" : "✗"}
      </summary>
      {Boolean(metadata.js_rendered_site) &&
        (metadata.js_render_used ? (
          <p className="mt-1.5 rounded border border-[var(--color-border)] bg-slate-50 px-2 py-1 text-[var(--color-text-muted)] dark:bg-slate-800/40">
            This site is JavaScript-rendered &mdash; it was loaded in a headless browser to read its content.
          </p>
        ) : (
          <p className="mt-1.5 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-amber-700 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
            This site is JavaScript-rendered and couldn't be read automatically &mdash; any details above came
            from RSPO or a web search.
          </p>
        ))}
      <ul className="mt-1.5 space-y-1 border-l border-[var(--color-border)] py-1 pl-3">
        {sources.map((s, i) => (
          <li key={i} className="flex items-center justify-between gap-3">
            {s.url ? (
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 flex-1 truncate text-[var(--color-accent)] hover:underline"
                title={s.found_via_search ? `Found via search: ${s.found_via_search}` : s.url}
              >
                {s.url}
              </a>
            ) : (
              <span className="min-w-0 flex-1 truncate text-[var(--color-text-muted)]" title={s.query}>
                Search: {s.query}
              </span>
            )}
            <span className="flex-shrink-0 text-[var(--color-text-muted)]">
              {s.rendered ? "🖥 " : ""}
              {STATUS_LABEL[s.status]}
            </span>
          </li>
        ))}
      </ul>
    </details>
  )
}
