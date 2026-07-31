import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api/client";
import { AuditSchema } from "../../lib/api/schemas";

export function useAudit(guildId: string) {
  return useQuery(auditQuery(guildId));
}

export function auditQuery(guildId: string) {
  return {
    queryKey: ["guild", guildId, "audit"] as const,
    queryFn: () => apiFetch(`/guilds/${guildId}/audit?limit=50`, AuditSchema),
    staleTime: 10_000,
    gcTime: 2 * 60_000,
    refetchInterval: 15_000,
  };
}
