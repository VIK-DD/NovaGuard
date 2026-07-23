import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { ApiError, apiFetch } from "../../lib/api/client";
import {
  GuildConfigSchema,
  type GuildSettings,
  type SettingsPatch,
} from "../../lib/api/schemas";
import BadwordsEditor from "../components/BadwordsEditor";
import ChannelSelect from "../components/ChannelSelect";
import RoleSelect from "../components/RoleSelect";
import SaveBar from "../components/SaveBar";
import { diffSettings, isDirty, mapValidationDetails } from "../lib/configForm";
import { useGuildConfig } from "../queries";

const CHANNEL_FIELDS: ReadonlyArray<
  [keyof Pick<
    GuildSettings,
    | "welcome_channel"
    | "goodbye_channel"
    | "log_channel"
    | "update_channel"
    | "github_event_channel"
    | "error_log_channel"
  >, string]
> = [
  ["welcome_channel", "Welcome channel"],
  ["goodbye_channel", "Goodbye channel"],
  ["log_channel", "Log channel"],
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
        className={`relative h-6 w-11 rounded-full transition-colors ${
          props.checked ? "bg-primary" : "bg-line"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
            props.checked ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
    </div>
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
          className="mt-6 rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-ink"
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
