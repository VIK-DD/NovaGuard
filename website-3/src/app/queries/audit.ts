import { infiniteQueryOptions, useInfiniteQuery } from "@tanstack/react-query";
import { apiFetch, pathSegment } from "../../lib/api/client";
import { AuditSchema } from "../../lib/api/schemas";

export interface AuditFilters {
  kind?: "settings" | "actions" | "login";
  actor?: string;
  after?: string;
  before?: string;
}

function auditPath(guildId: string, filters: AuditFilters, cursor?: number) {
  const params = new URLSearchParams({ limit: "50" });
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.actor) params.set("actor", filters.actor);
  if (filters.after) params.set("after", filters.after);
  if (filters.before) params.set("before", filters.before);
  if (cursor) params.set("cursor", String(cursor));
  return `/guilds/${pathSegment(guildId)}/audit?${params}`;
}

export function useAudit(guildId: string, filters: AuditFilters = {}) {
  return useInfiniteQuery(auditQuery(guildId, filters));
}

export function auditQuery(guildId: string, filters: AuditFilters = {}) {
  return infiniteQueryOptions({
    queryKey: ["guild", guildId, "audit", filters] as const,
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => apiFetch(auditPath(guildId, filters, pageParam), AuditSchema),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    staleTime: 10_000,
    gcTime: 2 * 60_000,
    refetchInterval: 15_000,
  });
}
