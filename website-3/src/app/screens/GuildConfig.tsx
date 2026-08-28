import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useBlocker, useParams } from "@tanstack/react-router";
import { ApiError, apiFetch } from "../../lib/api/client";
import {
  GuildConfigSchema,
  DashboardActionSchema,
  type GuildSettings,
  type SettingsPatch,
} from "../../lib/api/schemas";
import ChannelSelect from "../components/ChannelSelect";
import {
  LevelsSection,
  ModerationSection,
  UpdatesSection,
  VoiceSection,
  WelcomeSection,
} from "../components/ConfigCoreSections";
import { ModuleNav, Section } from "../components/ConfigPrimitives";
import { AiSection, EconomySection } from "../components/ConfigServiceSections";
import IgnoreListEditor from "../components/IgnoreListEditor";
import RoleSelect from "../components/RoleSelect";
import SaveBar from "../components/SaveBar";
import { diffSettings, isDirty, mapValidationDetails, validateSettings } from "../lib/configForm";
import {
  getConfigModule,
  isModuleActive,
} from "../moduleCatalog";
import { useGuildConfig } from "../queries/guilds";
import { useUnsavedChanges } from "../unsavedChanges";

const CHANNEL_FIELDS: ReadonlyArray<
  [keyof Pick<
    GuildSettings,
    | "welcome_channel"
    | "goodbye_channel"
    | "log_channel"
    | "voice_report_channel"
    | "update_channel"
    | "github_event_channel"
    | "error_log_channel"
    | "ticket_panel_channel"
    | "role_panel_channel"
    | "giveaway_channel"
  >, string]
> = [
  ["welcome_channel", "Welcome channel"],
  ["goodbye_channel", "Goodbye channel"],
  ["log_channel", "Log channel"],
  ["voice_report_channel", "Voice reports"],
  ["update_channel", "Update channel"],
  ["github_event_channel", "GitHub events"],
  ["error_log_channel", "Error log"],
  ["ticket_panel_channel", "Ticket panel"],
  ["role_panel_channel", "Role panels"],
  ["giveaway_channel", "Giveaways"],
];

export default function GuildConfig() {
  const { guildId, moduleId } = useParams({ strict: false }) as {
    guildId: string;
    moduleId?: string;
  };
  const selectedModule = getConfigModule(moduleId);
  const config = useGuildConfig(guildId);
  const qc = useQueryClient();
  const { registerUnsavedChanges } = useUnsavedChanges();
  const [draft, setDraft] = useState<GuildSettings | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [justSaved, setJustSaved] = useState(false);
  const [ticketPanelNotice, setTicketPanelNotice] = useState<string | null>(null);
  const [rolePanelTitle, setRolePanelTitle] = useState("");
  const [rolePanelDescription, setRolePanelDescription] = useState("");
  const [rolePanelRoleIds, setRolePanelRoleIds] = useState<string[]>([]);
  const [editingRolePanelId, setEditingRolePanelId] = useState<string | null>(null);
  const [rolePanelNotice, setRolePanelNotice] = useState<string | null>(null);
  const [giveawayPrize, setGiveawayPrize] = useState("");
  const [giveawayDuration, setGiveawayDuration] = useState("");
  const [giveawayWinners, setGiveawayWinners] = useState(1);
  const [giveawayNotice, setGiveawayNotice] = useState<string | null>(null);
  const [confirmGiveawayEndId, setConfirmGiveawayEndId] = useState<string | null>(null);

  // Reseed the draft whenever fresh server state arrives (fetch or save).
  useEffect(() => {
    if (config.data) setDraft(structuredClone(config.data.settings));
  }, [config.dataUpdatedAt]);

  // The "Saved" toast times out on its own rather than waiting for the next
  // save to clear it — SaveBar already gives `visible` (a new edit) priority
  // over `saved` in what it displays, so this timer only controls how long
  // the toast lingers when the visitor does nothing else.
  useEffect(() => {
    if (!justSaved) return;
    const id = setTimeout(() => setJustSaved(false), 2400);
    return () => clearTimeout(id);
  }, [justSaved]);

  const save = useMutation({
    mutationFn: (patch: SettingsPatch) =>
      apiFetch(`/guilds/${guildId}/config`, GuildConfigSchema, {
        method: "PUT",
        body: JSON.stringify(patch),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["guild", guildId, "config"], data);
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "dashboard"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "audit"] });
      setFieldErrors({});
      setJustSaved(true);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "validation_failed") {
        setFieldErrors(mapValidationDetails(err.details));
      }
    },
  });

  const publishTicketPanel = useMutation({
    mutationFn: () =>
      apiFetch(`/guilds/${guildId}/actions/ticket_panel_publish`, DashboardActionSchema, {
        method: "POST",
      }),
    onSuccess: (data) => {
      setTicketPanelNotice(data.message);
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "config"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "dashboard"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "audit"] });
    },
    onError: (error) => {
      setTicketPanelNotice(
        error instanceof ApiError ? error.message : "The ticket panel could not be published.",
      );
    },
  });

  const resetRolePanelDraft = useCallback(() => {
    setRolePanelTitle("");
    setRolePanelDescription("");
    setRolePanelRoleIds([]);
    setEditingRolePanelId(null);
  }, []);

  const publishRolePanel = useMutation({
    mutationFn: () =>
      apiFetch(`/guilds/${guildId}/actions/role_panel_publish`, DashboardActionSchema, {
        method: "POST",
        body: JSON.stringify({
          title: rolePanelTitle,
          description: rolePanelDescription,
          role_ids: rolePanelRoleIds,
          panel_message_id: editingRolePanelId,
        }),
      }),
    onSuccess: (data) => {
      setRolePanelNotice(data.message);
      resetRolePanelDraft();
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "config"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "dashboard"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "audit"] });
    },
    onError: (error) => {
      setRolePanelNotice(
        error instanceof ApiError ? error.message : "The role panel could not be published.",
      );
    },
  });

  const resetGiveawayDraft = useCallback(() => {
    setGiveawayPrize("");
    setGiveawayDuration("");
    setGiveawayWinners(1);
  }, []);

  const startGiveaway = useMutation({
    mutationFn: () =>
      apiFetch(`/guilds/${guildId}/actions/giveaway_start`, DashboardActionSchema, {
        method: "POST",
        body: JSON.stringify({
          prize: giveawayPrize,
          duration: giveawayDuration,
          winners: giveawayWinners,
        }),
      }),
    onSuccess: (data) => {
      setGiveawayNotice(data.message);
      setConfirmGiveawayEndId(null);
      resetGiveawayDraft();
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "config"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "dashboard"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "audit"] });
    },
    onError: (error) => {
      setGiveawayNotice(
        error instanceof ApiError ? error.message : "The giveaway could not be started.",
      );
    },
  });

  const manageGiveaway = useMutation({
    mutationFn: ({ action, messageId }: { action: "end" | "reroll"; messageId: string }) =>
      apiFetch(`/guilds/${guildId}/actions/giveaway_${action}`, DashboardActionSchema, {
        method: "POST",
        body: JSON.stringify({ message_id: messageId }),
      }),
    onMutate: () => startGiveaway.reset(),
    onSuccess: (data) => {
      setGiveawayNotice(data.message);
      setConfirmGiveawayEndId(null);
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "config"] });
      void qc.invalidateQueries({ queryKey: ["guild", guildId, "audit"] });
    },
    onError: (error) => {
      setGiveawayNotice(
        error instanceof ApiError ? error.message : "The giveaway action failed.",
      );
    },
  });

  const resetSave = save.reset;
  const clearErrors = useCallback(
    (keys: string[]) => {
      setFieldErrors((current) => {
        if (Object.keys(current).length === 0) return current;
        const next = { ...current };
        delete next._global;
        for (const key of keys) delete next[key];
        return next;
      });
      resetSave();
    },
    [resetSave],
  );

  // Stable identities (empty deps — the functional setDraft form needs no
  // closure over `draft`) so the memoized fields below can actually bail out
  // of re-rendering on an unrelated keystroke. A version of `set` closing over
  // `draft` would get a fresh identity every render, which would silently
  // defeat every React.memo below it: same props value, but a "new" onChange
  // reference each time reads as changed.
  //
  // Declared before the loading/error returns below, unlike the values that
  // depend on config.data — every hook here has to run on every render
  // regardless of which branch returns, or React throws on the next render
  // that takes a different branch.
  const set = useCallback(
    <K extends keyof GuildSettings>(key: K, value: GuildSettings[K]) => {
      clearErrors([String(key)]);
      setDraft((d) => (d ? { ...d, [key]: value } : d));
    },
    [clearErrors],
  );
  const setAutomod = useCallback(
    (patch: Partial<GuildSettings["automod"]>) => {
      clearErrors([
        "automod",
        "badwords",
        ...Object.keys(patch).map((key) => `automod.${key}`),
      ]);
      setDraft((d) => (d ? { ...d, automod: { ...d.automod, ...patch } } : d));
    },
    [clearErrors],
  );
  const setLevels = useCallback(
    (patch: Partial<GuildSettings["levels"]>) => {
      clearErrors(["levels", ...Object.keys(patch).map((key) => `levels.${key}`)]);
      setDraft((d) => (d ? { ...d, levels: { ...d.levels, ...patch } } : d));
    },
    [clearErrors],
  );
  const setAi = useCallback(
    (patch: Partial<GuildSettings["ai"]>) => {
      clearErrors(["ai", ...Object.keys(patch).map((key) => `ai.${key}`)]);
      setDraft((d) => (d ? { ...d, ai: { ...d.ai, ...patch } } : d));
    },
    [clearErrors],
  );
  const setEconomy = useCallback(
    (patch: Partial<GuildSettings["economy"]>) => {
      clearErrors(["economy", ...Object.keys(patch).map((key) => `economy.${key}`)]);
      setDraft((d) => (d ? { ...d, economy: { ...d.economy, ...patch } } : d));
    },
    [clearErrors],
  );

  // One stable handler per channel field, built off the stable `set` above —
  // built once, not one fresh arrow function per field per render.
  const channelFieldHandlers = useMemo(
    () =>
      Object.fromEntries(
        CHANNEL_FIELDS.map(([key]) => [key, (v: string | null) => set(key, v)]),
      ) as Record<(typeof CHANNEL_FIELDS)[number][0], (v: string | null) => void>,
    [set],
  );
  const onAutoroleChange = useCallback((v: string | null) => set("autorole", v), [set]);
  const onTicketRoleChange = useCallback(
    (v: string | null) => set("ticket_staff_role", v),
    [set],
  );
  const onInvitesChange = useCallback((v: boolean) => setAutomod({ invites: v }), [setAutomod]);
  const onSpamChange = useCallback((v: boolean) => setAutomod({ spam: v }), [setAutomod]);
  const onBadwordsChange = useCallback(
    (v: string[]) => setAutomod({ badwords: v }),
    [setAutomod],
  );
  const onAutomodIgnoredChannelsChange = useCallback(
    (v: string[]) => setAutomod({ ignored_channels: v }),
    [setAutomod],
  );
  const onAutomodIgnoredRolesChange = useCallback(
    (v: string[]) => setAutomod({ ignored_roles: v }),
    [setAutomod],
  );
  const onSpamMessagesChange = useCallback(
    (v: number) => setAutomod({ spam_messages: v }),
    [setAutomod],
  );
  const onSpamWindowChange = useCallback(
    (v: number) => setAutomod({ spam_window_seconds: v }),
    [setAutomod],
  );
  const onSpamTimeoutChange = useCallback(
    (v: number) => setAutomod({ spam_timeout_seconds: v }),
    [setAutomod],
  );
  const onLevelsEnabledChange = useCallback((v: boolean) => setLevels({ enabled: v }), [setLevels]);
  const onAnnounceChange = useCallback(
    (value: GuildSettings["levels"]["announce"]) => setLevels({ announce: value }),
    [setLevels],
  );
  const onAnnounceChannelChange = useCallback(
    (v: string | null) => setLevels({ announce_channel: v }),
    [setLevels],
  );
  const onXpMinChange = useCallback((v: number) => setLevels({ xp_min: v }), [setLevels]);
  const onXpMaxChange = useCallback((v: number) => setLevels({ xp_max: v }), [setLevels]);
  const onCooldownChange = useCallback((v: number) => setLevels({ cooldown: v }), [setLevels]);
  const onIgnoredChannelsChange = useCallback(
    (v: string[]) => setLevels({ ignored_channels: v }),
    [setLevels],
  );
  const onIgnoredRolesChange = useCallback(
    (v: string[]) => setLevels({ ignored_roles: v }),
    [setLevels],
  );
  const onAiEnabledChange = useCallback(
    (value: boolean) => setAi({ enabled: value }),
    [setAi],
  );
  const onAiChannelChange = useCallback(
    (value: string | null) => setAi({ channel_id: value }),
    [setAi],
  );
  const onAiAnswerModeChange = useCallback(
    (value: GuildSettings["ai"]["answer_mode"]) => setAi({ answer_mode: value }),
    [setAi],
  );
  const onAiQuestionLimitChange = useCallback(
    (value: number) => setAi({ max_question_chars: value }),
    [setAi],
  );

  const dirty = Boolean(config.data && draft && isDirty(config.data.settings, draft));
  const rolePanelDirty = Boolean(
    rolePanelTitle || rolePanelDescription || rolePanelRoleIds.length || editingRolePanelId,
  );
  const giveawayDirty = Boolean(
    giveawayPrize || giveawayDuration || giveawayWinners !== 1,
  );
  const hasUnsavedChanges = dirty || rolePanelDirty || giveawayDirty;
  const discardDraft = useCallback(() => {
    if (!config.data) return;
    setDraft(structuredClone(config.data.settings));
    setFieldErrors({});
    resetRolePanelDraft();
    resetGiveawayDraft();
    resetSave();
  }, [config.data, resetGiveawayDraft, resetRolePanelDraft, resetSave]);

  useEffect(() => {
    registerUnsavedChanges(hasUnsavedChanges, discardDraft);
    return () => registerUnsavedChanges(false);
  }, [hasUnsavedChanges, discardDraft, registerUnsavedChanges]);

  const blocker = useBlocker({
    shouldBlockFn: () => hasUnsavedChanges,
    enableBeforeUnload: hasUnsavedChanges,
    withResolver: true,
  });

  useEffect(() => {
    if (blocker.status !== "blocked") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") blocker.reset();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [blocker]);

  if (config.isPending || (config.data && !draft)) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16" aria-busy="true">
        <div className="h-8 w-1/3 animate-pulse rounded bg-line/60" />
      </main>
    );
  }

  if (config.isError || !config.data || !draft) {
    const code = config.error instanceof ApiError ? config.error.code : "internal_error";
    const retryable = code !== "forbidden" && code !== "guild_not_found";
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16">
        <h1 className="font-display text-3xl">
          {code === "forbidden"
            ? "You need Manage Server here."
            : code === "guild_not_found"
              ? "NovaGuard is not in this server."
              : "Could not load this server."}
        </h1>
        <p className="mt-3 max-w-lg text-sm text-ink-muted">
          {code === "forbidden"
            ? "Choose a server where you have Manage Server permission."
            : code === "guild_not_found"
              ? "Choose another server or add NovaGuard again before configuring it."
              : "Check the connection and try once more."}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {retryable && (
            <button
              onClick={() => void config.refetch()}
              className="ng-touch-target inline-flex items-center rounded-full bg-primary px-5 py-2 text-sm text-primary-ink transition-opacity hover:opacity-90"
            >
              Try again
            </button>
          )}
          <Link
            to="/"
            className="ng-touch-target inline-flex items-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-ink"
          >
            Back to servers
          </Link>
        </div>
      </main>
    );
  }

  const { guild, channels, roles, settings } = config.data;
  const saveError =
    save.error instanceof ApiError && save.error.code !== "validation_failed"
      ? save.error.message
      : fieldErrors._global;

  const saveDraft = () => {
    const localErrors = validateSettings(draft);
    if (Object.keys(localErrors).length > 0) {
      setFieldErrors(localErrors);
      resetSave();
      requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      });
      return;
    }
    save.mutate(diffSettings(settings, draft));
  };

  return (
    <>
      <main className="mx-auto max-w-5xl px-4 pt-8 pb-36 sm:px-6 sm:pt-10 sm:pb-32">
        {selectedModule && (
          <Link
            to="/g/$guildId/settings"
            params={{ guildId }}
            className="ng-touch-target -ml-2 mb-5 inline-flex items-center gap-2 rounded-md px-2 text-sm text-ink-muted transition-colors hover:text-ink"
          >
            <span aria-hidden="true">←</span>
            All modules
          </Link>
        )}
        <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">
          {guild.member_count.toLocaleString("en")} members
        </p>
        <h1 className="font-display mt-2 break-words text-3xl sm:text-4xl">
          {selectedModule ? `${selectedModule.label} · ${guild.name}` : `Modules for ${guild.name}`}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-muted">
          {selectedModule
            ? `${selectedModule.description} Changes stay local until you save them.`
            : "Choose one feature to configure. Each module has its own focused page, and every saved update is recorded in the audit log."}
        </p>

        {!moduleId && <ModuleNav guildId={guildId} settings={draft} />}

        {moduleId && !selectedModule && (
          <section className="mt-8 rounded-[var(--radius-card)] border border-line bg-card p-6">
            <p className="text-xs tracking-[0.2em] text-primary uppercase">Unknown module</p>
            <h2 className="font-display mt-2 text-2xl">This configuration module does not exist.</h2>
            <p className="mt-2 text-sm text-ink-muted">
              The link may be outdated. Return to the module list to choose an available feature.
            </p>
            <Link
              to="/g/$guildId/settings"
              params={{ guildId }}
              className="ng-touch-target mt-5 inline-flex items-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink"
            >
              View all modules
            </Link>
          </section>
        )}

        <div className="mt-8 grid gap-5">
          {selectedModule?.key === "welcome" && (
            <WelcomeSection
              settings={draft}
              channels={channels}
              roles={roles}
              fieldErrors={fieldErrors}
              onWelcomeChannelChange={channelFieldHandlers.welcome_channel}
              onGoodbyeChannelChange={channelFieldHandlers.goodbye_channel}
              onAutoroleChange={onAutoroleChange}
            />
          )}

          {selectedModule?.key === "moderation" && (
            <ModerationSection
              settings={draft}
              channels={channels}
              roles={roles}
              fieldErrors={fieldErrors}
              onLogChannelChange={channelFieldHandlers.log_channel}
              onErrorLogChannelChange={channelFieldHandlers.error_log_channel}
              onInvitesChange={onInvitesChange}
              onSpamChange={onSpamChange}
              onBadwordsChange={onBadwordsChange}
              onIgnoredChannelsChange={onAutomodIgnoredChannelsChange}
              onIgnoredRolesChange={onAutomodIgnoredRolesChange}
              onSpamMessagesChange={onSpamMessagesChange}
              onSpamWindowChange={onSpamWindowChange}
              onSpamTimeoutChange={onSpamTimeoutChange}
            />
          )}

          {selectedModule?.key === "levels" && (
            <LevelsSection
              settings={draft}
              channels={channels}
              roles={roles}
              fieldErrors={fieldErrors}
              onEnabledChange={onLevelsEnabledChange}
              onAnnounceChange={onAnnounceChange}
              onAnnounceChannelChange={onAnnounceChannelChange}
              onXpMinChange={onXpMinChange}
              onXpMaxChange={onXpMaxChange}
              onCooldownChange={onCooldownChange}
              onIgnoredChannelsChange={onIgnoredChannelsChange}
              onIgnoredRolesChange={onIgnoredRolesChange}
            />
          )}

          {selectedModule?.key === "voice" && (
            <VoiceSection
              settings={draft}
              channels={channels}
              fieldErrors={fieldErrors}
              onChange={channelFieldHandlers.voice_report_channel}
            />
          )}

          {selectedModule?.key === "tickets" && (
            <Section
            id="tickets"
            icon="clipboard-text"
            kicker="Tickets"
            description="Choose which role can claim and manage member support tickets."
            active={isModuleActive(draft, "tickets")}
          >
            <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
              <ChannelSelect
                label="Ticket panel channel"
                value={draft.ticket_panel_channel}
                channels={channels}
                error={fieldErrors.ticket_panel_channel}
                onChange={channelFieldHandlers.ticket_panel_channel}
              />
              <RoleSelect
                label="Ticket staff role"
                value={draft.ticket_staff_role}
                roles={roles.filter(
                  (role) => role.manages_threads || role.id === draft.ticket_staff_role,
                )}
                error={fieldErrors.ticket_staff_role}
                onChange={onTicketRoleChange}
              />
            </div>
            <p className="mt-2 text-xs leading-5 text-ink-muted">
              Only roles with <strong>Manage Threads</strong> are offered. The selected role also
              needs <strong>View Channel</strong> in the panel channel.
            </p>
            <div className="mt-6 rounded-lg border border-line bg-bg-subtle p-4">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium">
                    {config.data.tickets.panel_message_id ? "Panel is live" : "Panel not published"}
                  </p>
                  <p className="mt-1 text-xs leading-5 text-ink-muted">
                    {dirty
                      ? "Save these settings before publishing the panel."
                      : config.data.tickets.ready
                        ? "Publishing again updates the existing message instead of creating a duplicate."
                        : "Choose both fields above, save, then publish."}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={
                    dirty ||
                    !draft.ticket_panel_channel ||
                    !draft.ticket_staff_role ||
                    publishTicketPanel.isPending
                  }
                  onClick={() => {
                    setTicketPanelNotice(null);
                    publishTicketPanel.mutate();
                  }}
                  className="ng-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {publishTicketPanel.isPending
                    ? "Publishing…"
                    : config.data.tickets.panel_message_id
                      ? "Update panel"
                      : "Publish panel"}
                </button>
              </div>
              {ticketPanelNotice && (
                <p
                  role={publishTicketPanel.isError ? "alert" : "status"}
                  className={`mt-3 border-t border-line pt-3 text-sm ${
                    publishTicketPanel.isError ? "text-primary" : "text-good"
                  }`}
                >
                  {ticketPanelNotice}
                </p>
              )}
            </div>

            <div className="mt-6 border-t border-line pt-5">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium">Open tickets</p>
                <span className="rounded-full border border-line bg-bg-subtle px-2.5 py-1 text-xs text-ink-muted">
                  {config.data.tickets.open_count}
                </span>
              </div>
              {config.data.tickets.open.length > 0 ? (
                <ul className="mt-3 divide-y divide-line border-y border-line">
                  {config.data.tickets.open.map((ticket) => (
                    <li key={ticket.thread_id} className="flex items-center justify-between gap-3 py-3">
                      <span className="min-w-0">
                        <span className="block truncate text-sm text-ink">{ticket.opener_name}</span>
                        <span className="mt-0.5 block text-xs text-ink-faint">
                          Opened {new Date(ticket.created_at).toLocaleString("en-US")}
                        </span>
                      </span>
                      <a
                        href={`https://discord.com/channels/${guildId}/${ticket.thread_id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="ng-touch-target inline-flex shrink-0 items-center rounded-md px-2 text-sm text-primary hover:underline"
                      >
                        Open in Discord ↗
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-ink-muted">No tracked tickets are open.</p>
              )}
            </div>
            </Section>
          )}

          {selectedModule?.key === "roles" && (
            <Section
              id="roles"
              icon="users-three"
              kicker="Role panels"
              description="Let members add and remove safe, self-service roles without staff intervention."
              active={isModuleActive(draft, "roles")}
            >
              <div className="max-w-md border-t border-line pt-6">
                <ChannelSelect
                  label="Default panel channel"
                  value={draft.role_panel_channel}
                  channels={channels}
                  error={fieldErrors.role_panel_channel}
                  onChange={channelFieldHandlers.role_panel_channel}
                />
                <p className="mt-2 text-xs leading-5 text-ink-muted">
                  Save a new default channel before publishing a new panel. Existing panels stay in
                  their original channel when edited.
                </p>
              </div>

              <div className="mt-7 rounded-lg border border-line bg-bg-subtle p-4 sm:p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">
                      {editingRolePanelId ? "Edit role panel" : "Create role panel"}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-ink-muted">
                      One panel can offer up to five roles that NovaGuard is allowed to assign.
                    </p>
                  </div>
                  {editingRolePanelId && (
                    <button
                      type="button"
                      onClick={() => {
                        resetRolePanelDraft();
                        setRolePanelNotice(null);
                      }}
                      className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-ink"
                    >
                      Cancel editing
                    </button>
                  )}
                </div>

                <div className="mt-5 grid gap-5">
                  <label className="block">
                    <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                      Panel title
                    </span>
                    <input
                      value={rolePanelTitle}
                      maxLength={80}
                      onChange={(event) => {
                        setRolePanelTitle(event.target.value);
                        setRolePanelNotice(null);
                      }}
                      placeholder="Community roles"
                      className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
                    />
                    <span className="mt-1 block text-right text-xs text-ink-faint">
                      {rolePanelTitle.length}/80
                    </span>
                  </label>

                  <label className="block">
                    <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                      Description
                    </span>
                    <textarea
                      value={rolePanelDescription}
                      maxLength={1000}
                      rows={4}
                      onChange={(event) => {
                        setRolePanelDescription(event.target.value);
                        setRolePanelNotice(null);
                      }}
                      placeholder="Choose the roles that match what you want to follow."
                      className="mt-1.5 w-full resize-y rounded-md border border-line bg-card px-3 py-2 text-sm leading-6 outline-none focus:border-ink"
                    />
                    <span className="mt-1 block text-right text-xs text-ink-faint">
                      {rolePanelDescription.length}/1000
                    </span>
                  </label>

                  <IgnoreListEditor
                    label="Self-assignable roles"
                    prefix="@"
                    value={rolePanelRoleIds}
                    options={roles.filter(
                      (role) => role.assignable || rolePanelRoleIds.includes(role.id),
                    )}
                    maxItems={5}
                    onChange={(value) => {
                      setRolePanelRoleIds(value);
                      setRolePanelNotice(null);
                    }}
                  />
                </div>

                <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-ink-muted">
                    {dirty
                      ? "Save the channel change before publishing."
                      : editingRolePanelId
                        ? "The tracked Discord message will be updated in place."
                        : "Publishing creates one persistent Discord message."}
                  </p>
                  <button
                    type="button"
                    disabled={
                      dirty ||
                      (!editingRolePanelId && !draft.role_panel_channel) ||
                      !rolePanelTitle.trim() ||
                      !rolePanelDescription.trim() ||
                      rolePanelRoleIds.length === 0 ||
                      publishRolePanel.isPending
                    }
                    onClick={() => {
                      setRolePanelNotice(null);
                      publishRolePanel.mutate();
                    }}
                    className="ng-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {publishRolePanel.isPending
                      ? "Publishing…"
                      : editingRolePanelId
                        ? "Update panel"
                        : "Publish panel"}
                  </button>
                </div>

                {rolePanelNotice && (
                  <p
                    role={publishRolePanel.isError ? "alert" : "status"}
                    className={`mt-3 border-t border-line pt-3 text-sm ${
                      publishRolePanel.isError ? "text-primary" : "text-good"
                    }`}
                  >
                    {rolePanelNotice}
                  </p>
                )}
              </div>

              <div className="mt-7 border-t border-line pt-5">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">Tracked panels</p>
                  <span className="rounded-full border border-line bg-bg-subtle px-2.5 py-1 text-xs text-ink-muted">
                    {config.data.role_panels.length}
                  </span>
                </div>
                {config.data.role_panels.length > 0 ? (
                  <ul className="mt-3 divide-y divide-line border-y border-line">
                    {config.data.role_panels.map((panel) => {
                      const channel = channels.find((item) => item.id === panel.channel_id);
                      return (
                        <li
                          key={panel.message_id}
                          className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-ink">{panel.title}</span>
                            <span className="mt-0.5 block text-xs text-ink-faint">
                              #{channel?.name ?? "deleted-channel"} · {panel.role_ids.length} roles ·
                              updated {new Date(panel.updated_at).toLocaleString("en-US")}
                            </span>
                          </span>
                          <span className="flex shrink-0 items-center gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setEditingRolePanelId(panel.message_id);
                                setRolePanelTitle(panel.title);
                                setRolePanelDescription(panel.description);
                                setRolePanelRoleIds(panel.role_ids);
                                setRolePanelNotice(null);
                              }}
                              className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-ink"
                            >
                              Edit
                            </button>
                            <a
                              href={`https://discord.com/channels/${guildId}/${panel.channel_id}/${panel.message_id}`}
                              target="_blank"
                              rel="noreferrer"
                              className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-primary hover:underline"
                            >
                              Open ↗
                            </a>
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-ink-muted">No role panels are tracked yet.</p>
                )}
              </div>
            </Section>
          )}

          {selectedModule?.key === "giveaways" && (
            <Section
              id="giveaways"
              icon="trophy"
              kicker="Giveaways"
              description="Create timed draws, watch entry counts and manage results from one place."
              active={isModuleActive(draft, "giveaways")}
            >
              <div className="max-w-md border-t border-line pt-6">
                <ChannelSelect
                  label="Giveaway channel"
                  value={draft.giveaway_channel}
                  channels={channels}
                  error={fieldErrors.giveaway_channel}
                  onChange={channelFieldHandlers.giveaway_channel}
                />
              </div>

              <div className="mt-7 rounded-lg border border-line bg-bg-subtle p-4 sm:p-5">
                <p className="text-sm font-medium">Start a giveaway</p>
                <p className="mt-1 text-xs leading-5 text-ink-muted">
                  Durations accept combinations such as 30m, 1h 30m or 2d, from one minute to 30
                  days.
                </p>
                <div className="mt-5 grid gap-5 sm:grid-cols-[minmax(0,1fr)_9rem_8rem]">
                  <label className="block">
                    <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                      Prize
                    </span>
                    <input
                      value={giveawayPrize}
                      maxLength={200}
                      onChange={(event) => {
                        setGiveawayPrize(event.target.value);
                        setGiveawayNotice(null);
                      }}
                      placeholder="One month of Nitro"
                      className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                      Duration
                    </span>
                    <input
                      value={giveawayDuration}
                      maxLength={40}
                      onChange={(event) => {
                        setGiveawayDuration(event.target.value);
                        setGiveawayNotice(null);
                      }}
                      placeholder="1d"
                      className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
                    />
                  </label>
                  <label className="block">
                    <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                      Winners
                    </span>
                    <input
                      type="number"
                      min={1}
                      max={10}
                      step={1}
                      value={giveawayWinners}
                      onChange={(event) => {
                        setGiveawayWinners(Number(event.target.value));
                        setGiveawayNotice(null);
                      }}
                      className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
                    />
                  </label>
                </div>
                <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-xs leading-5 text-ink-muted">
                    {dirty
                      ? "Save the channel change before starting."
                      : "The draw closes automatically and announces winners in this channel."}
                  </p>
                  <button
                    type="button"
                    disabled={
                      dirty ||
                      !draft.giveaway_channel ||
                      !giveawayPrize.trim() ||
                      !giveawayDuration.trim() ||
                      !Number.isInteger(giveawayWinners) ||
                      giveawayWinners < 1 ||
                      giveawayWinners > 10 ||
                      startGiveaway.isPending
                    }
                    onClick={() => {
                      setGiveawayNotice(null);
                      manageGiveaway.reset();
                      startGiveaway.mutate();
                    }}
                    className="ng-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {startGiveaway.isPending ? "Starting…" : "Start giveaway"}
                  </button>
                </div>
                {giveawayNotice && (
                  <p
                    role={startGiveaway.isError || manageGiveaway.isError ? "alert" : "status"}
                    className={`mt-3 border-t border-line pt-3 text-sm ${
                      startGiveaway.isError || manageGiveaway.isError
                        ? "text-primary"
                        : "text-good"
                    }`}
                  >
                    {giveawayNotice}
                  </p>
                )}
              </div>

              <div className="mt-7 border-t border-line pt-5">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium">Active giveaways</p>
                  <span className="rounded-full border border-line bg-bg-subtle px-2.5 py-1 text-xs text-ink-muted">
                    {config.data.giveaways.filter((giveaway) => !giveaway.ended).length}
                  </span>
                </div>
                {config.data.giveaways.some((giveaway) => !giveaway.ended) ? (
                  <ul className="mt-3 divide-y divide-line border-y border-line">
                    {config.data.giveaways
                      .filter((giveaway) => !giveaway.ended)
                      .map((giveaway) => {
                        const channel = channels.find((item) => item.id === giveaway.channel_id);
                        const isPending =
                          manageGiveaway.isPending &&
                          manageGiveaway.variables?.messageId === giveaway.message_id;
                        const isConfirming = confirmGiveawayEndId === giveaway.message_id;
                        return (
                          <li
                            key={giveaway.message_id}
                            className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-sm text-ink">{giveaway.prize}</span>
                              <span className="mt-0.5 block text-xs text-ink-faint">
                                #{channel?.name ?? "deleted-channel"} · {giveaway.entrant_count} entries ·
                                ends {new Date(giveaway.ends_at).toLocaleString("en-US")}
                              </span>
                            </span>
                            <span className="flex shrink-0 flex-wrap items-center gap-2">
                              <a
                                href={`https://discord.com/channels/${guildId}/${giveaway.channel_id}/${giveaway.message_id}`}
                                target="_blank"
                                rel="noreferrer"
                                className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-primary hover:underline"
                              >
                                Open ↗
                              </a>
                              {isConfirming ? (
                                <>
                                  <button
                                    type="button"
                                    disabled={isPending}
                                    onClick={() => setConfirmGiveawayEndId(null)}
                                    className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-ink"
                                  >
                                    Cancel
                                  </button>
                                  <button
                                    type="button"
                                    disabled={isPending}
                                    onClick={() =>
                                      manageGiveaway.mutate({
                                        action: "end",
                                        messageId: giveaway.message_id,
                                      })
                                    }
                                    className="ng-touch-target inline-flex items-center rounded-full border border-primary px-4 py-2 text-sm text-primary disabled:opacity-45"
                                  >
                                    {isPending ? "Ending…" : "Confirm end"}
                                  </button>
                                </>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => setConfirmGiveawayEndId(giveaway.message_id)}
                                  className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-primary"
                                >
                                  End early
                                </button>
                              )}
                            </span>
                          </li>
                        );
                      })}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-ink-muted">No giveaways are active.</p>
                )}
              </div>

              <div className="mt-7 border-t border-line pt-5">
                <p className="text-sm font-medium">Recent results</p>
                {config.data.giveaways.some((giveaway) => giveaway.ended) ? (
                  <ul className="mt-3 divide-y divide-line border-y border-line">
                    {config.data.giveaways
                      .filter((giveaway) => giveaway.ended)
                      .map((giveaway) => {
                        const isPending =
                          manageGiveaway.isPending &&
                          manageGiveaway.variables?.messageId === giveaway.message_id;
                        return (
                          <li
                            key={giveaway.message_id}
                            className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
                          >
                            <span className="min-w-0">
                              <span className="block truncate text-sm text-ink">{giveaway.prize}</span>
                              <span className="mt-0.5 block text-xs text-ink-faint">
                                {giveaway.entrant_count} entries · {giveaway.winner_ids.length} recorded
                                winner{giveaway.winner_ids.length === 1 ? "" : "s"}
                              </span>
                            </span>
                            <button
                              type="button"
                              disabled={giveaway.entrant_count === 0 || isPending}
                              onClick={() =>
                                manageGiveaway.mutate({
                                  action: "reroll",
                                  messageId: giveaway.message_id,
                                })
                              }
                              className="ng-touch-target inline-flex shrink-0 items-center rounded-full border border-line px-4 py-2 text-sm transition-colors hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-45"
                            >
                              {isPending ? "Rerolling…" : "Reroll"}
                            </button>
                          </li>
                        );
                      })}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm text-ink-muted">No completed giveaways yet.</p>
                )}
              </div>
            </Section>
          )}

          {selectedModule?.key === "ai" && (
            <AiSection
              settings={draft}
              status={config.data.ai_status}
              channels={channels}
              fieldErrors={fieldErrors}
              onEnabledChange={onAiEnabledChange}
              onChannelChange={onAiChannelChange}
              onAnswerModeChange={onAiAnswerModeChange}
              onQuestionLimitChange={onAiQuestionLimitChange}
            />
          )}

          {selectedModule?.key === "economy" && (
            <EconomySection
              settings={draft}
              status={config.data.economy_status}
              fieldErrors={fieldErrors}
              onChange={setEconomy}
            />
          )}

          {selectedModule?.key === "updates" && (
            <UpdatesSection
              settings={draft}
              channels={channels}
              fieldErrors={fieldErrors}
              onUpdateChannelChange={channelFieldHandlers.update_channel}
              onGithubChannelChange={channelFieldHandlers.github_event_channel}
            />
          )}
        </div>

        <SaveBar
          visible={dirty}
          saving={save.isPending}
          saved={justSaved}
          error={saveError}
          onSave={saveDraft}
          onDiscard={discardDraft}
        />
      </main>

      {blocker.status === "blocked" && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-5 py-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) blocker.reset();
          }}
        >
          <section
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="leave-settings-title"
            aria-describedby="leave-settings-description"
            className="w-full max-w-md rounded-[var(--radius-card)] border border-line bg-background p-6 shadow-[0_24px_80px_rgb(0_0_0/0.4)]"
          >
            <p className="text-xs tracking-[0.2em] text-primary uppercase">Unsaved changes</p>
            <h2 id="leave-settings-title" className="font-display mt-2 text-2xl font-semibold">
              Leave without saving?
            </h2>
            <p id="leave-settings-description" className="mt-3 text-sm leading-6 text-ink-muted">
              Your recent configuration changes will be discarded.
            </p>
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={blocker.proceed}
                className="ng-touch-target inline-flex items-center justify-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-line-strong"
              >
                Discard and leave
              </button>
              <button
                type="button"
                autoFocus
                onClick={blocker.reset}
                className="ng-touch-target inline-flex items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90"
              >
                Keep editing
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
