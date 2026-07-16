import { useMutation, useQueryClient } from "@tanstack/react-query"
import { setStage } from "@/api/pipeline"
import type { PipelineStage } from "@/types/domain"

/** The single mutation the table's stage dropdown calls for every row. */
export function useMoveStageMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ schoolId, stage }: { schoolId: number; stage: PipelineStage }) => setStage(schoolId, stage),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline"] })
      queryClient.invalidateQueries({ queryKey: ["school"] })
      queryClient.invalidateQueries({ queryKey: ["pipeline-queue"] })
      queryClient.invalidateQueries({ queryKey: ["pipeline-map"] })
    },
  })
}
