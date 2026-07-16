import { useEffect, useRef } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { listRecentJobs } from "@/api/enrichment"
import { queryKeys } from "@/api/queryKeys"

export function useRecentEnrichmentJobs() {
  const queryClient = useQueryClient()
  const notifiedDoneIds = useRef<Set<number>>(new Set())

  const query = useQuery({
    queryKey: queryKeys.enrichmentJobs(),
    queryFn: listRecentJobs,
    refetchInterval: (q) => {
      const jobs = q.state.data ?? []
      const hasActive = jobs.some((j) => j.status === "pending" || j.status === "running")
      return hasActive ? 2500 : false
    },
  })

  // A job finishing in the background must be reflected wherever its
  // schools are shown (director/contacts/activity log/library score) --
  // otherwise the drawer just sits there looking stale until some
  // unrelated refetch happens to pick up the change.
  useEffect(() => {
    const jobs = query.data ?? []
    const newlyDone = jobs.filter((j) => j.status === "done" && !notifiedDoneIds.current.has(j.id))
    if (newlyDone.length === 0) return
    newlyDone.forEach((j) => notifiedDoneIds.current.add(j.id))
    queryClient.invalidateQueries({ queryKey: ["school"] })
    queryClient.invalidateQueries({ queryKey: ["school-contacts"] })
    queryClient.invalidateQueries({ queryKey: ["activity"] })
    queryClient.invalidateQueries({ queryKey: ["schools"] })
  }, [query.data, queryClient])

  return query
}
