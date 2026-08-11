import { memo, useCallback, useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useBlocker, useParams } from "@tanstack/react-router";
import { ApiError, apiFetch } from "../../lib/api/client";
import {
  GuildConfigSchema,
  DashboardActionSchema,
  type AnnounceMode,
  type GuildSettings,
  type SettingsPatch,
} from "../../lib/api/schemas";
import BadwordsEditor from "../components/BadwordsEditor";
import ChannelSelect from "../components/ChannelSelect";
import Icon, { type IconName } from "../components/Icon";
import IgnoreListEditor from "../components/IgnoreListEditor";
import RoleSelect from "../components/RoleSelect";
import SaveBar from "../components/SaveBar";
import { diffSettings, isDirty, mapValidationDetails, validateSettings } from "../lib/configForm";
import {
  CONFIG_MODULES,
  getConfigModule,
  isModuleActive,
  type ConfigModuleKey,
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
];

// Memoized like the field components in components/ — see the note in
// ChannelSelect.tsx. Only worth it once the caller also hands these a stable
// onChange identity, which the callbacks below are built to provide.
const Toggle = memo(function Toggle(props: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between border-t border-line py-4">
      <span className="text-sm">{props.label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={props.checked}
        aria-label={props.label}
        onClick={() => props.onChange(!props.checked)}
        className="ng-touch-target grid h-11 w-12 shrink-0 appearance-none place-items-center rounded-[8px] p-0"
      >
        <span
          aria-hidden="true"
          className={`relative block h-6 w-11 shrink-0 rounded-full border p-[2px] transition-[background-color,border-color] duration-150 ${
            props.checked ? "border-primary bg-primary" : "border-line-strong bg-card"
          }`}
        >
          <span
            className={`block h-[18px] w-[18px] rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.22)] transition-transform duration-150 ease-out ${
              props.checked ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </span>
      </button>
    </div>
  );
});

const NumberField = memo(function NumberField(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  error?: string;
  onChange: (value: number) => void;
}) {
  // Held as text while editing so the field can be cleared and retyped. A
  // number-only state would snap the old value back on the first keystroke of
  // a two-digit edit. Blur reconciles with whatever was actually committed.
  const [text, setText] = useState(String(props.value));
  const [editing, setEditing] = useState(false);
  const inputId = useId();
  const errorId = `${inputId}-error`;

  useEffect(() => {
    if (!editing) setText(String(props.value));
  }, [editing, props.value]);

  return (
    <div className="block">
      <label htmlFor={inputId} className="text-xs tracking-[0.15em] text-ink-muted uppercase">
        {props.label}
        {props.suffix && <span className="normal-case"> ({props.suffix})</span>}
      </label>
      <input
        id={inputId}
        type="number"
        inputMode="numeric"
        min={props.min}
        max={props.max}
        value={text}
        aria-invalid={props.error ? true : undefined}
        aria-describedby={props.error ? errorId : undefined}
        onFocus={() => setEditing(true)}
        onChange={(e) => {
          setText(e.target.value);
          const parsed = Number(e.target.value);
          if (e.target.value !== "" && Number.isInteger(parsed)) props.onChange(parsed);
        }}
        onBlur={() => {
          setEditing(false);
          setText(String(props.value));
        }}
        className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
          props.error ? "border-primary" : "border-line"
        }`}
      />
      {props.error && (
        <p id={errorId} className="text-primary mt-1 text-xs">
          {props.error}
        </p>
      )}
    </div>
  );
});

function Section(props: {
  id: ConfigModuleKey;
  icon: IconName;
  kicker: string;
  description: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      id={props.id}
      aria-labelledby={`${props.id}-title`}
      className="scroll-mt-6 rounded-[var(--radius-card)] border border-line bg-card p-5 shadow-[0_1px_0_hsl(0_0%_100%/0.03)_inset] sm:p-6"
    >
      <div className="flex items-start gap-3.5">
        <span className="bg-line/40 grid h-10 w-10 shrink-0 place-items-center rounded-[8px] border border-line text-ink">
          <Icon name={props.icon} size={20} />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p id={`${props.id}-title`} className="text-xs tracking-[0.2em] text-primary uppercase">
              {props.kicker}
            </p>
            <span
              className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                props.active
                  ? "border-good/35 bg-good/10 text-good"
                  : "border-line bg-bg-subtle text-ink-muted"
              }`}
            >
              {props.active ? "Active" : "Not configured"}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-muted">{props.description}</p>
        </div>
      </div>
      <div className="mt-6">{props.children}</div>
    </section>
  );
}

function ModuleNav({ guildId, settings }: { guildId: string; settings: GuildSettings }) {
  return (
    <nav aria-label="Configuration modules" className="mt-8 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {CONFIG_MODULES.map((module) => {
        const active = isModuleActive(settings, module.key);
        return (
          <Link
            key={module.key}
            to="/g/$guildId/settings/$moduleId"
            params={{ guildId, moduleId: module.key }}
            className="ng-pressable group flex min-h-[5.5rem] items-start gap-3 rounded-[var(--radius-card)] border border-line bg-card p-4 transition-colors hover:border-line-strong"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[8px] border border-line bg-bg-subtle text-ink">
              <Icon name={module.icon} size={18} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{module.label}</span>
                <span
                  aria-label={active ? "Active" : "Not configured"}
                  className={`h-2 w-2 shrink-0 rounded-full ${active ? "bg-good" : "bg-line-strong"}`}
                />
              </span>
              <span className="mt-1 line-clamp-2 block text-xs leading-5 text-ink-muted">
                {module.description}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

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

  const dirty = Boolean(config.data && draft && isDirty(config.data.settings, draft));
  const discardDraft = useCallback(() => {
    if (!config.data) return;
    setDraft(structuredClone(config.data.settings));
    setFieldErrors({});
    resetSave();
  }, [config.data, resetSave]);

  useEffect(() => {
    registerUnsavedChanges(dirty, discardDraft);
    return () => registerUnsavedChanges(false);
  }, [dirty, discardDraft, registerUnsavedChanges]);

  const blocker = useBlocker({
    shouldBlockFn: () => dirty,
    enableBeforeUnload: dirty,
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
            <Section
            id="welcome"
            icon="users-three"
            kicker="Welcome"
            description="Greet new members, announce departures and assign a starter role."
            active={isModuleActive(draft, "welcome")}
          >
            <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
              <ChannelSelect
                label="Welcome channel"
                value={draft.welcome_channel}
                channels={channels}
                error={fieldErrors.welcome_channel}
                onChange={channelFieldHandlers.welcome_channel}
              />
              <ChannelSelect
                label="Goodbye channel"
                value={draft.goodbye_channel}
                channels={channels}
                error={fieldErrors.goodbye_channel}
                onChange={channelFieldHandlers.goodbye_channel}
              />
              <RoleSelect
                label="Auto-role for newcomers"
                value={draft.autorole}
                roles={roles.filter((role) => role.assignable)}
                error={fieldErrors.autorole}
                onChange={onAutoroleChange}
              />
            </div>
            </Section>
          )}

          {selectedModule?.key === "moderation" && (
            <Section
            id="moderation"
            icon="shield-check"
            kicker="Moderation"
            description="Filter unwanted messages and keep staff-facing activity in the right channels."
            active={isModuleActive(draft, "moderation")}
          >
            <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
              <ChannelSelect
                label="Server log channel"
                value={draft.log_channel}
                channels={channels}
                error={fieldErrors.log_channel}
                onChange={channelFieldHandlers.log_channel}
              />
              <ChannelSelect
                label="Error log channel"
                value={draft.error_log_channel}
                channels={channels}
                error={fieldErrors.error_log_channel}
                onChange={channelFieldHandlers.error_log_channel}
              />
            </div>
            <div className="mt-6 border-t border-line pt-2">
              <Toggle
                label="Block Discord invites"
                checked={draft.automod.invites}
                onChange={onInvitesChange}
              />
              <Toggle label="Anti-spam" checked={draft.automod.spam} onChange={onSpamChange} />
              <div className="border-t border-line pt-4">
                <BadwordsEditor
                  value={draft.automod.badwords}
                  error={
                    fieldErrors["automod.badwords"] ?? fieldErrors.badwords ?? fieldErrors.automod
                  }
                  onChange={onBadwordsChange}
                />
              </div>
              <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-3">
                <NumberField
                  label="Messages"
                  suffix="to trigger"
                  value={draft.automod.spam_messages}
                  min={3}
                  max={20}
                  error={fieldErrors["automod.spam_messages"]}
                  onChange={onSpamMessagesChange}
                />
                <NumberField
                  label="Detection window"
                  suffix="seconds"
                  value={draft.automod.spam_window_seconds}
                  min={2}
                  max={60}
                  error={fieldErrors["automod.spam_window_seconds"]}
                  onChange={onSpamWindowChange}
                />
                <NumberField
                  label="Timeout"
                  suffix="seconds"
                  value={draft.automod.spam_timeout_seconds}
                  min={10}
                  max={86400}
                  error={fieldErrors["automod.spam_timeout_seconds"]}
                  onChange={onSpamTimeoutChange}
                />
              </div>
              <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
                <IgnoreListEditor
                  label="Channels exempt from AutoMod"
                  prefix="#"
                  value={draft.automod.ignored_channels}
                  options={channels}
                  error={fieldErrors["automod.ignored_channels"]}
                  onChange={onAutomodIgnoredChannelsChange}
                />
                <IgnoreListEditor
                  label="Roles exempt from AutoMod"
                  prefix="@"
                  value={draft.automod.ignored_roles}
                  options={roles}
                  error={fieldErrors["automod.ignored_roles"]}
                  onChange={onAutomodIgnoredRolesChange}
                />
              </div>
            </div>
            </Section>
          )}

          {selectedModule?.key === "levels" && (
            <Section
            id="levels"
            icon="trophy"
            kicker="Levels"
            description="Reward server activity with XP and level-up announcements."
            active={isModuleActive(draft, "levels")}
          >
            <Toggle
              label="Give XP for messages"
              checked={draft.levels.enabled}
              onChange={onLevelsEnabledChange}
            />
            <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
              <label className="block">
                <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                  Level-up announcement
                </span>
                <select
                  value={draft.levels.announce}
                  aria-invalid={fieldErrors["levels.announce"] ? true : undefined}
                  onChange={(event) => setLevels({ announce: event.target.value as AnnounceMode })}
                  className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
                    fieldErrors["levels.announce"] ? "border-primary" : "border-line"
                  }`}
                >
                  <option value="dm">Direct message</option>
                  <option value="channel">In a channel</option>
                  <option value="off">Don't announce</option>
                </select>
                {fieldErrors["levels.announce"] && (
                  <p className="text-primary mt-1 text-xs">{fieldErrors["levels.announce"]}</p>
                )}
              </label>
              {draft.levels.announce === "channel" && (
                <ChannelSelect
                  label="Announcement channel"
                  value={draft.levels.announce_channel}
                  channels={channels}
                  error={fieldErrors["levels.announce_channel"]}
                  onChange={onAnnounceChannelChange}
                />
              )}
            </div>
            <div className="mt-5 grid gap-5 sm:grid-cols-3">
              <NumberField
                label="XP minimum"
                value={draft.levels.xp_min}
                min={1}
                max={100}
                error={fieldErrors["levels.xp_min"]}
                onChange={onXpMinChange}
              />
              <NumberField
                label="XP maximum"
                value={draft.levels.xp_max}
                min={1}
                max={100}
                error={fieldErrors["levels.xp_max"]}
                onChange={onXpMaxChange}
              />
              <NumberField
                label="Cooldown"
                suffix="seconds"
                value={draft.levels.cooldown}
                min={0}
                max={3600}
                error={fieldErrors["levels.cooldown"]}
                onChange={onCooldownChange}
              />
            </div>
            <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
              <IgnoreListEditor
                label="Channels without XP"
                prefix="#"
                value={draft.levels.ignored_channels}
                options={channels}
                error={fieldErrors["levels.ignored_channels"]}
                onChange={onIgnoredChannelsChange}
              />
              <IgnoreListEditor
                label="Roles without XP"
                prefix="@"
                value={draft.levels.ignored_roles}
                options={roles}
                error={fieldErrors["levels.ignored_roles"]}
                onChange={onIgnoredRolesChange}
              />
            </div>
            </Section>
          )}

          {selectedModule?.key === "voice" && (
            <Section
            id="voice"
            icon="users-three"
            kicker="Voice reports"
            description="Choose where completed voice-session reports are published."
            active={isModuleActive(draft, "voice")}
          >
            <div className="max-w-md border-t border-line pt-6">
              <ChannelSelect
                label="Voice report channel"
                value={draft.voice_report_channel}
                channels={channels}
                error={fieldErrors.voice_report_channel}
                onChange={channelFieldHandlers.voice_report_channel}
              />
            </div>
            </Section>
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

          {selectedModule?.key === "updates" && (
            <Section
            id="updates"
            icon="arrows-clockwise"
            kicker="Updates"
            description="Route NovaGuard releases and repository activity into this server."
            active={isModuleActive(draft, "updates")}
          >
            <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
              <ChannelSelect
                label="NovaGuard update channel"
                value={draft.update_channel}
                channels={channels}
                error={fieldErrors.update_channel}
                onChange={channelFieldHandlers.update_channel}
              />
              <ChannelSelect
                label="GitHub event channel"
                value={draft.github_event_channel}
                channels={channels}
                error={fieldErrors.github_event_channel}
                onChange={channelFieldHandlers.github_event_channel}
              />
            </div>
            </Section>
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
              Your recent settings changes will be discarded.
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
