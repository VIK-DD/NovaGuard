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
    queryKey: ["me"],
    queryFn: () => apiFetch("/me", MeSchema),
    retry: false,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch("/auth/logout", OkSchema, { method: "POST" }),
    onSettled: () => qc.invalidateQueries(),
  });
}

export function useGuilds() {
  return useQuery({
    queryKey: ["guilds"],
    queryFn: () => apiFetch("/guilds", GuildsSchema),
  });
}

export function useGuildConfig(guildId: string) {
  return useQuery({
    queryKey: ["guild", guildId, "config"],
    queryFn: () => apiFetch(`/guilds/${guildId}/config`, GuildConfigSchema),
  });
}

export function useAudit(guildId: string) {
  return useQuery({
    queryKey: ["guild", guildId, "audit"],
    queryFn: () => apiFetch(`/guilds/${guildId}/audit?limit=50`, AuditSchema),
  });
}
