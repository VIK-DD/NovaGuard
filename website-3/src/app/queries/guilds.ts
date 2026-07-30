import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api/client";
import { DashboardActionSchema, DashboardSchema, GuildConfigSchema, GuildsSchema } from "../../lib/api/schemas";

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

export function useGuildDashboard(guildId: string) {
  return useQuery(guildDashboardQuery(guildId));
}

export function guildDashboardQuery(guildId: string) {
  return {
    queryKey: ["guild", guildId, "dashboard"] as const,
    queryFn: () => apiFetch(`/guilds/${guildId}/dashboard`, DashboardSchema),
    staleTime: 20_000,
    gcTime: 2 * 60_000,
    refetchInterval: 30_000,
  };
}

export function runGuildAction(guildId: string, action: string) {
  return apiFetch(`/guilds/${guildId}/actions/${action}`, DashboardActionSchema, {
    method: "POST",
  });
}
