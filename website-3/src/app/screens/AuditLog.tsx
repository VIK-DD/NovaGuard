import { Link, useParams } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import type { AuditEntry } from "../../lib/api/schemas";
import Icon from "../components/Icon";
import { type AuditFilters, useAudit } from "../queries/audit";

const dateFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
});

const ACTION_META: Record<string, { label: string; detail: string; tone: "good" | "warn" | "muted" }> = {
  config_update: {
    label: "Settings saved",
    detail: "Configuration changed from the dashboard.",
    tone: "good",
  },
  dashboard_backup_check: {
    label: "Backup checked",
    detail: "The latest archive was verified from the dashboard.",
    tone: "good",
  },
  dashboard_voice_test: {
    label: "Voice test sent",
    detail: "A preview voice report was posted to Discord.",
    tone: "good",
  },
  dashboard_update_preview: {
    label: "Update preview sent",
    detail: "The newest saved update was posted to this server.",
    tone: "good",
  },
  login: {
    label: "Signed in",
    detail: "Dashboard session started.",
    tone: "muted",
  },
  update_automod: {
    label: "AutoMod updated",
    detail: "Mock dashboard event.",
    tone: "good",
  },
  update_channels: {
    label: "Channels updated",
    detail: "Mock dashboard event.",
    tone: "good",
  },
  update_roles: {
    label: "Roles updated",
    detail: "Mock dashboard event.",
    tone: "good",
  },
};

function actionMeta(action: string) {
  return (
    ACTION_META[action] ?? {
      label: action.replaceAll("_", " "),
      detail: "Dashboard activity recorded.",
      tone: "muted" as const,
    }
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(", ") : "empty";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function ActivityRow({ entry }: { entry: AuditEntry }) {
  const meta = actionMeta(entry.action);
  const changes = Object.entries(entry.changes);
  const dot =
    meta.tone === "good"
      ? "border-good/35 bg-good/15 text-good"
      : meta.tone === "warn"
        ? "border-primary/35 bg-primary-soft text-primary"
        : "border-line bg-bg-subtle text-ink-muted";

  return (
    <li className="grid gap-3 border-t border-line py-5 sm:grid-cols-[8rem_1fr]">
      <time className="text-xs text-ink-muted sm:pt-1">{dateFmt.format(new Date(entry.created_at))}</time>
      <div className="min-w-0">
        <div className="flex items-start gap-3">
          <span className={`mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full border ${dot}`}>
            <Icon name="hash" size={15} flat />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
              <p className="font-display text-base font-semibold">{meta.label}</p>
              <p className="text-xs text-ink-muted">by {entry.username}</p>
            </div>
            <p className="mt-1 text-sm text-ink-muted">{meta.detail}</p>
            {changes.length > 0 && (
              <ul className="mt-3 flex flex-wrap gap-2">
                {changes.map(([key, value]) => (
                  <li key={key}>
                    <code className="block max-w-full break-all rounded-md border border-line bg-card px-2.5 py-1 text-xs whitespace-normal">
                      {key}: {formatValue(value)}
                    </code>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

export default function AuditLog() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const [draft, setDraft] = useState({ kind: "", actor: "", after: "", before: "" });
  const [filters, setFilters] = useState<AuditFilters>({});
  const audit = useAudit(guildId, filters);
  const entries = useMemo(
    () => audit.data?.pages.flatMap((page) => page.audit) ?? [],
    [audit.data],
  );
  const actionCount = entries.filter((entry) => entry.action.startsWith("dashboard_")).length;
  const settingsCount = entries.filter((entry) => entry.action === "config_update" || entry.action.startsWith("update_")).length;
  const hasFilters = Object.values(filters).some(Boolean);

  const applyFilters = () => {
    const next: AuditFilters = {};
    if (draft.kind) next.kind = draft.kind as AuditFilters["kind"];
    if (draft.actor.trim()) next.actor = draft.actor.trim();
    if (draft.after) next.after = `${draft.after}T00:00:00.000Z`;
    if (draft.before) {
      const exclusiveEnd = new Date(`${draft.before}T00:00:00.000Z`);
      exclusiveEnd.setUTCDate(exclusiveEnd.getUTCDate() + 1);
      next.before = exclusiveEnd.toISOString();
    }
    setFilters(next);
  };

  const clearFilters = () => {
    setDraft({ kind: "", actor: "", after: "", before: "" });
    setFilters({});
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-col gap-4 border-b border-line pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs tracking-[0.25em] text-primary uppercase">Audit log</p>
          <h1 className="font-display mt-2 text-3xl font-semibold tracking-tight">Dashboard activity</h1>
          <p className="mt-2 max-w-2xl text-sm text-ink-muted">
            Tracks dashboard saves and quick actions. Discord chat moderation logs still live in your configured log channel.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void audit.refetch()}
          disabled={audit.isFetching}
          className="ng-pressable inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-line bg-card px-4 text-sm hover:border-line-strong disabled:opacity-60"
        >
          <Icon name="arrows-clockwise" size={17} flat />
          {audit.isFetching ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <section className="mt-5 rounded-[var(--radius-card)] border border-line bg-card p-4 sm:p-5">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-[1fr_1fr_0.8fr_0.8fr_auto] lg:items-end">
          <label className="grid gap-1.5 text-xs font-medium text-ink-muted">
            Event type
            <select
              value={draft.kind}
              onChange={(event) => setDraft((current) => ({ ...current, kind: event.target.value }))}
              className="min-h-11 rounded-lg border border-line bg-bg px-3 text-sm text-ink outline-none focus:border-primary"
            >
              <option value="">All events</option>
              <option value="settings">Settings</option>
              <option value="actions">Quick actions</option>
              <option value="login">Sign-ins</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-xs font-medium text-ink-muted">
            Actor
            <input
              type="search"
              value={draft.actor}
              onChange={(event) => setDraft((current) => ({ ...current, actor: event.target.value }))}
              placeholder="Name or Discord ID"
              maxLength={100}
              className="min-h-11 rounded-lg border border-line bg-bg px-3 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-primary"
            />
          </label>
          <label className="grid gap-1.5 text-xs font-medium text-ink-muted">
            From
            <input
              type="date"
              value={draft.after}
              onChange={(event) => setDraft((current) => ({ ...current, after: event.target.value }))}
              className="min-h-11 rounded-lg border border-line bg-bg px-3 text-sm text-ink outline-none focus:border-primary"
            />
          </label>
          <label className="grid gap-1.5 text-xs font-medium text-ink-muted">
            Through
            <input
              type="date"
              value={draft.before}
              onChange={(event) => setDraft((current) => ({ ...current, before: event.target.value }))}
              className="min-h-11 rounded-lg border border-line bg-bg px-3 text-sm text-ink outline-none focus:border-primary"
            />
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={applyFilters}
              className="ng-pressable min-h-11 rounded-full bg-primary px-4 text-sm font-medium text-primary-ink"
            >
              Apply
            </button>
            {(hasFilters || Object.values(draft).some(Boolean)) && (
              <button
                type="button"
                onClick={clearFilters}
                className="ng-pressable min-h-11 rounded-full border border-line px-4 text-sm"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </section>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-[var(--radius-card)] border border-line bg-card p-4">
          <p className="text-xs tracking-[0.16em] text-ink-muted uppercase">Events</p>
          <p className="font-display mt-2 text-2xl font-semibold">{entries.length}</p>
        </div>
        <div className="rounded-[var(--radius-card)] border border-line bg-card p-4">
          <p className="text-xs tracking-[0.16em] text-ink-muted uppercase">Quick actions</p>
          <p className="font-display mt-2 text-2xl font-semibold">{actionCount}</p>
        </div>
        <div className="rounded-[var(--radius-card)] border border-line bg-card p-4">
          <p className="text-xs tracking-[0.16em] text-ink-muted uppercase">Settings</p>
          <p className="font-display mt-2 text-2xl font-semibold">{settingsCount}</p>
        </div>
      </div>

      {audit.isPending && (
        <div className="mt-6" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse border-t border-line py-5">
              <div className="h-5 w-2/3 rounded bg-line/60" />
              <div className="mt-2 h-4 w-1/2 rounded bg-line/40" />
            </div>
          ))}
        </div>
      )}

      {audit.isError && (
        <p className="mt-6 rounded-[var(--radius-card)] border border-line bg-card p-4 text-sm text-ink-muted">
          Could not load the audit log.{" "}
          <button onClick={() => void audit.refetch()} className="ng-touch-target inline-flex items-center underline hover:text-ink">
            Try again
          </button>
        </p>
      )}

      {audit.data && entries.length === 0 && (
        <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-card p-6">
          <p className="font-display text-xl font-semibold">
            {hasFilters ? "No activity matches these filters." : "No dashboard activity yet."}
          </p>
          <p className="mt-2 text-sm text-ink-muted">
            {hasFilters
              ? "Clear the filters or choose a wider date range."
              : "Run a quick action or change a setting and the event will appear here automatically."}
          </p>
          <Link
            to="/g/$guildId"
            params={{ guildId }}
            className="ng-pressable mt-5 inline-flex min-h-11 items-center rounded-full border border-line px-4 text-sm hover:border-line-strong"
          >
            Back to overview
          </Link>
        </div>
      )}

      {entries.length > 0 && (
        <ul className="mt-6">
          {entries.map((entry) => (
            <ActivityRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}

      {audit.hasNextPage && (
        <div className="mt-4 flex justify-center border-t border-line pt-5">
          <button
            type="button"
            onClick={() => void audit.fetchNextPage()}
            disabled={audit.isFetchingNextPage}
            className="ng-pressable min-h-11 rounded-full border border-line bg-card px-5 text-sm hover:border-line-strong disabled:opacity-60"
          >
            {audit.isFetchingNextPage ? "Loading..." : "Load older activity"}
          </button>
        </div>
      )}
    </main>
  );
}
