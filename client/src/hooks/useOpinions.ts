import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { 
  fetchOpinions, 
  syncOpinions, 
  ingestOpinion,
  fetchStatus 
} from "@/lib/api";

export function useOpinions(options?: {
  status?: string;
  limit?: number;
  ingested?: boolean;
}) {
  return useQuery({
    queryKey: ["opinions", options],
    queryFn: () => fetchOpinions(options),
    staleTime: 60000,
  });
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    staleTime: 30000,
  });
}

export function useSyncOpinions() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: syncOpinions,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["opinions"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

export function useIngestOpinion() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: ingestOpinion,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["opinions"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
}
