import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../lib/api/client";
import {
  AuditSchema,
  GuildConfigSchema,
  GuildsSchema,
  MeSchema,
  OkSchema,
} from "../lib/api/schemas";

export function useMe() {
  return useQuery({
    ...meQuery(),
    retry: false,
  });
}

export function meQuery() {
  return {
    queryKey: ["me"] as const,
    queryFn: () => apiFetch("/me", MeSchema),
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
  };
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch("/auth/logout", OkSchema, { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      window.location.assign("/dashboard/");
    },
  });
}

export function useGuilds() {
  return useQuery(guildsQuery());
}

export function guildsQuery() {
  return {
    queryKey: ["guilds"] as const,
    queryFn: () => apiFetch("/guilds", GuildsSchema),
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
  };
}

export function useGuildConfig(guildId: string) {
  return useQuery(guildConfigQuery(guildId));
}

export function guildConfigQuery(guildId: string) {
  return {
    queryKey: ["guild", guildId, "config"] as const,
    queryFn: () => apiFetch(`/guilds/${guildId}/config`, GuildConfigSchema),
    staleTime: 2 * 60_000,
    gcTime: 3 * 60_000,
  };
}

export function useAudit(guildId: string) {
  return useQuery(auditQuery(guildId));
}

export function auditQuery(guildId: string) {
  return {
    queryKey: ["guild", guildId, "audit"] as const,
    queryFn: () => apiFetch(`/guilds/${guildId}/audit?limit=50`, AuditSchema),
    staleTime: 30_000,
    gcTime: 2 * 60_000,
  };
}
