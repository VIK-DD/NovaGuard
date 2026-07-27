import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { ApiError, apiFetch } from "../../lib/api/client";
import {
  GuildConfigSchema,
  type AnnounceMode,
  type GuildSettings,
  type SettingsPatch,
} from "../../lib/api/schemas";
import BadwordsEditor from "../components/BadwordsEditor";
import ChannelSelect from "../components/ChannelSelect";
import IgnoreListEditor from "../components/IgnoreListEditor";
import RoleSelect from "../components/RoleSelect";
import SaveBar from "../components/SaveBar";
import { diffSettings, isDirty, mapValidationDetails } from "../lib/configForm";
import { useGuildConfig } from "../queries/guilds";

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
  >, string]
> = [
  ["welcome_channel", "Welcome channel"],
  ["goodbye_channel", "Goodbye channel"],
  ["log_channel", "Log channel"],
  ["voice_report_channel", "Voice reports"],
  ["update_channel", "Update channel"],
  ["github_event_channel", "GitHub events"],
  ["error_log_channel", "Error log"],
];

function Toggle(props: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
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
}

function NumberField(props: {
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
  if (!editing && text !== String(props.value)) setText(String(props.value));

  return (
    <label className="block">
      <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
        {props.label}
        {props.suffix && <span className="normal-case"> ({props.suffix})</span>}
      </span>
      <input
        type="number"
        inputMode="numeric"
        min={props.min}
        max={props.max}
        value={text}
        aria-invalid={props.error ? true : undefined}
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
      {props.error && <p className="text-primary mt-1 text-xs">{props.error}</p>}
    </label>
  );
}

function Section(props: { kicker: string; children: React.ReactNode }) {
  return (
    <section className="mt-12">
      <p className="text-xs tracking-[0.2em] text-primary uppercase">{props.kicker}</p>
      <div className="mt-4">{props.children}</div>
    </section>
  );
}

export default function GuildConfig() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const config = useGuildConfig(guildId);
  const qc = useQueryClient();
  const [draft, setDraft] = useState<GuildSettings | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // Reseed the draft whenever fresh server state arrives (fetch or save).
  useEffect(() => {
    if (config.data) setDraft(structuredClone(config.data.settings));
  }, [config.dataUpdatedAt]);

  const save = useMutation({
    mutationFn: (patch: SettingsPatch) =>
      apiFetch(`/guilds/${guildId}/config`, GuildConfigSchema, {
        method: "PUT",
        body: JSON.stringify(patch),
      }),
    onSuccess: (data) => {
      qc.setQueryData(["guild", guildId, "config"], data);
      setFieldErrors({});
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "validation_failed") {
        setFieldErrors(mapValidationDetails(err.details));
      }
    },
  });

  if (config.isPending || (config.data && !draft)) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16" aria-busy="true">
        <div className="h-8 w-1/3 animate-pulse rounded bg-line/60" />
      </main>
    );
  }

  if (config.isError || !config.data || !draft) {
    const code = config.error instanceof ApiError ? config.error.code : "internal_error";
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16">
        <h1 className="font-display text-3xl">
          {code === "forbidden"
            ? "You need Manage Server here."
            : code === "guild_not_found"
              ? "NovaGuard is not in this server."
              : "Could not load this server."}
        </h1>
        <button
          onClick={() => void config.refetch()}
          className="ng-touch-target mt-6 inline-flex items-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-ink"
        >
          Retry
        </button>
      </main>
    );
  }

  const { guild, channels, roles, settings } = config.data;
  const dirty = isDirty(settings, draft);
  const saveError =
    save.error instanceof ApiError && save.error.code !== "validation_failed"
      ? save.error.message
      : fieldErrors._global;

  const set = <K extends keyof GuildSettings>(key: K, value: GuildSettings[K]) =>
    setDraft({ ...draft, [key]: value });

  const setLevels = (patch: Partial<GuildSettings["levels"]>) =>
    setDraft({ ...draft, levels: { ...draft.levels, ...patch } });

  return (
    <main className="mx-auto max-w-3xl px-4 pt-8 pb-36 sm:px-6 sm:pt-10 sm:pb-32">
      <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">
        {guild.member_count.toLocaleString("en")} members
      </p>
      <h1 className="font-display mt-2 break-words text-3xl sm:text-4xl">{guild.name}</h1>

      <Section kicker="Channels">
        <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
          {CHANNEL_FIELDS.map(([key, label]) => (
            <ChannelSelect
              key={key}
              label={label}
              value={draft[key]}
              channels={channels}
              error={fieldErrors[key]}
              onChange={(v) => set(key, v)}
            />
          ))}
        </div>
      </Section>

      <Section kicker="Roles">
        <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
          <RoleSelect
            label="Auto-role for newcomers"
            value={draft.autorole}
            roles={roles.filter((r) => r.assignable)}
            error={fieldErrors.autorole}
            onChange={(v) => set("autorole", v)}
          />
          <RoleSelect
            label="Ticket staff role"
            value={draft.ticket_staff_role}
            roles={roles}
            error={fieldErrors.ticket_staff_role}
            onChange={(v) => set("ticket_staff_role", v)}
          />
        </div>
      </Section>

      <Section kicker="AutoMod">
        <Toggle
          label="Block Discord invites"
          checked={draft.automod.invites}
          onChange={(v) => set("automod", { ...draft.automod, invites: v })}
        />
        <Toggle
          label="Anti-spam"
          checked={draft.automod.spam}
          onChange={(v) => set("automod", { ...draft.automod, spam: v })}
        />
        <div className="border-t border-line pt-4">
          <BadwordsEditor
            value={draft.automod.badwords}
            error={fieldErrors.badwords ?? fieldErrors.automod}
            onChange={(v) => set("automod", { ...draft.automod, badwords: v })}
          />
        </div>
      </Section>

      <Section kicker="Levels">
        <Toggle
          label="Give XP for messages"
          checked={draft.levels.enabled}
          onChange={(v) => setLevels({ enabled: v })}
        />
        <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
              Level-up announcement
            </span>
            <select
              value={draft.levels.announce}
              aria-invalid={fieldErrors["levels.announce"] ? true : undefined}
              onChange={(e) => setLevels({ announce: e.target.value as AnnounceMode })}
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
              onChange={(v) => setLevels({ announce_channel: v })}
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
            onChange={(v) => setLevels({ xp_min: v })}
          />
          <NumberField
            label="XP maximum"
            value={draft.levels.xp_max}
            min={1}
            max={100}
            error={fieldErrors["levels.xp_max"]}
            onChange={(v) => setLevels({ xp_max: v })}
          />
          <NumberField
            label="Cooldown"
            suffix="seconds"
            value={draft.levels.cooldown}
            min={0}
            max={3600}
            error={fieldErrors["levels.cooldown"]}
            onChange={(v) => setLevels({ cooldown: v })}
          />
        </div>
        <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
          <IgnoreListEditor
            label="Channels without XP"
            prefix="#"
            value={draft.levels.ignored_channels}
            options={channels}
            error={fieldErrors["levels.ignored_channels"]}
            onChange={(v) => setLevels({ ignored_channels: v })}
          />
          <IgnoreListEditor
            label="Roles without XP"
            prefix="@"
            value={draft.levels.ignored_roles}
            options={roles}
            error={fieldErrors["levels.ignored_roles"]}
            onChange={(v) => setLevels({ ignored_roles: v })}
          />
        </div>
      </Section>

      <SaveBar
        visible={dirty}
        saving={save.isPending}
        error={saveError}
        onSave={() => save.mutate(diffSettings(settings, draft))}
        onDiscard={() => {
          setDraft(structuredClone(settings));
          setFieldErrors({});
          save.reset();
        }}
      />
    </main>
  );
}
