import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MeResponseSchema, OkResponseSchema } from "./authSchemas";
import { apiFetch } from "../lib/api/client";

export function useMe() {
  return useQuery({
    ...meQuery(),
    retry: false,
  });
}

export function meQuery() {
  return {
    queryKey: ["me"] as const,
    queryFn: () => apiFetch("/me", MeResponseSchema),
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
  };
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch("/auth/logout", OkResponseSchema, { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      window.location.assign("/dashboard/");
    },
  });
}
