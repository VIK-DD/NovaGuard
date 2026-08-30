import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useBlocker, useParams } from "@tanstack/react-router";
import { ApiError, apiFetch, pathSegment } from "../../lib/api/client";
import {
  GuildConfigSchema,
  DashboardActionSchema,
  type GuildConfig as GuildConfigPayload,
  type GuildSettings,
  type SettingsPatch,
} from "../../lib/api/schemas";
import {
  LevelsSection,
  ModerationSection,
  UpdatesSection,
  VoiceSection,
  WelcomeSection,
} from "../components/ConfigCoreSections";
import { GiveawaySection } from "../components/ConfigGiveawaySection";
import { ModuleNav } from "../components/ConfigPrimitives";
import { RolePanelsSection } from "../components/ConfigRolePanelsSection";
import { AiSection, EconomySection } from "../components/ConfigServiceSections";
import { TicketSection } from "../components/ConfigTicketSection";
import SaveBar from "../components/SaveBar";
import { diffSettings, isDirty, mapValidationDetails, validateSettings } from "../lib/configForm";
import { getConfigModule } from "../moduleCatalog";
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
      apiFetch(`/guilds/${pathSegment(guildId)}/config`, GuildConfigSchema, {
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
      apiFetch(`/guilds/${pathSegment(guildId)}/actions/ticket_panel_publish`, DashboardActionSchema, {
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
      apiFetch(`/guilds/${pathSegment(guildId)}/actions/role_panel_publish`, DashboardActionSchema, {
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
      apiFetch(`/guilds/${pathSegment(guildId)}/actions/giveaway_start`, DashboardActionSchema, {
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
      apiFetch(`/guilds/${pathSegment(guildId)}/actions/giveaway_${pathSegment(action)}`, DashboardActionSchema, {
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
  const publishTicketPanelAction = publishTicketPanel.mutate;
  const publishRolePanelAction = publishRolePanel.mutate;
  const startGiveawayAction = startGiveaway.mutate;
  const resetGiveawayAction = manageGiveaway.reset;
  const manageGiveawayAction = manageGiveaway.mutate;
  const onTicketPanelPublish = useCallback(() => {
    setTicketPanelNotice(null);
    publishTicketPanelAction();
  }, [publishTicketPanelAction]);
  const onRolePanelTitleChange = useCallback((value: string) => {
    setRolePanelTitle(value);
    setRolePanelNotice(null);
  }, []);
  const onRolePanelDescriptionChange = useCallback((value: string) => {
    setRolePanelDescription(value);
    setRolePanelNotice(null);
  }, []);
  const onRolePanelRoleIdsChange = useCallback((value: string[]) => {
    setRolePanelRoleIds(value);
    setRolePanelNotice(null);
  }, []);
  const onRolePanelCancel = useCallback(() => {
    resetRolePanelDraft();
    setRolePanelNotice(null);
  }, [resetRolePanelDraft]);
  const onRolePanelEdit = useCallback((panel: GuildConfigPayload["role_panels"][number]) => {
    setEditingRolePanelId(panel.message_id);
    setRolePanelTitle(panel.title);
    setRolePanelDescription(panel.description);
    setRolePanelRoleIds(panel.role_ids);
    setRolePanelNotice(null);
  }, []);
  const onRolePanelPublish = useCallback(() => {
    setRolePanelNotice(null);
    publishRolePanelAction();
  }, [publishRolePanelAction]);
  const onGiveawayPrizeChange = useCallback((value: string) => {
    setGiveawayPrize(value);
    setGiveawayNotice(null);
  }, []);
  const onGiveawayDurationChange = useCallback((value: string) => {
    setGiveawayDuration(value);
    setGiveawayNotice(null);
  }, []);
  const onGiveawayWinnersChange = useCallback((value: number) => {
    setGiveawayWinners(value);
    setGiveawayNotice(null);
  }, []);
  const onGiveawayStart = useCallback(() => {
    setGiveawayNotice(null);
    resetGiveawayAction();
    startGiveawayAction();
  }, [resetGiveawayAction, startGiveawayAction]);
  const onGiveawayEnd = useCallback(
    (messageId: string) => manageGiveawayAction({ action: "end", messageId }),
    [manageGiveawayAction],
  );
  const onGiveawayReroll = useCallback(
    (messageId: string) => manageGiveawayAction({ action: "reroll", messageId }),
    [manageGiveawayAction],
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
            <TicketSection
              guildId={guildId}
              settings={draft}
              tickets={config.data.tickets}
              channels={channels}
              roles={roles}
              fieldErrors={fieldErrors}
              dirty={dirty}
              publishPending={publishTicketPanel.isPending}
              publishError={publishTicketPanel.isError}
              notice={ticketPanelNotice}
              onChannelChange={channelFieldHandlers.ticket_panel_channel}
              onRoleChange={onTicketRoleChange}
              onPublish={onTicketPanelPublish}
            />
          )}

          {selectedModule?.key === "roles" && (
            <RolePanelsSection
              guildId={guildId}
              settings={draft}
              panels={config.data.role_panels}
              channels={channels}
              roles={roles}
              fieldErrors={fieldErrors}
              dirty={dirty}
              title={rolePanelTitle}
              description={rolePanelDescription}
              roleIds={rolePanelRoleIds}
              editingId={editingRolePanelId}
              notice={rolePanelNotice}
              publishPending={publishRolePanel.isPending}
              publishError={publishRolePanel.isError}
              onChannelChange={channelFieldHandlers.role_panel_channel}
              onTitleChange={onRolePanelTitleChange}
              onDescriptionChange={onRolePanelDescriptionChange}
              onRoleIdsChange={onRolePanelRoleIdsChange}
              onCancelEdit={onRolePanelCancel}
              onEdit={onRolePanelEdit}
              onPublish={onRolePanelPublish}
            />
          )}

          {selectedModule?.key === "giveaways" && (
            <GiveawaySection
              guildId={guildId}
              settings={draft}
              giveaways={config.data.giveaways}
              channels={channels}
              fieldErrors={fieldErrors}
              dirty={dirty}
              prize={giveawayPrize}
              duration={giveawayDuration}
              winners={giveawayWinners}
              notice={giveawayNotice}
              confirmEndId={confirmGiveawayEndId}
              startPending={startGiveaway.isPending}
              startError={startGiveaway.isError}
              managePending={manageGiveaway.isPending}
              manageError={manageGiveaway.isError}
              managingMessageId={manageGiveaway.variables?.messageId ?? null}
              onChannelChange={channelFieldHandlers.giveaway_channel}
              onPrizeChange={onGiveawayPrizeChange}
              onDurationChange={onGiveawayDurationChange}
              onWinnersChange={onGiveawayWinnersChange}
              onStart={onGiveawayStart}
              onConfirmEndChange={setConfirmGiveawayEndId}
              onEnd={onGiveawayEnd}
              onReroll={onGiveawayReroll}
            />
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
