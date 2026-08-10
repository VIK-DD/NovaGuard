import { Link, useParams } from "@tanstack/react-router";
import type { AuditEntry } from "../../lib/api/schemas";
import Icon from "../components/Icon";
import { useAudit } from "../queries/audit";

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
  const audit = useAudit(guildId);
  const entries = audit.data?.audit ?? [];
  const actionCount = entries.filter((entry) => entry.action.startsWith("dashboard_")).length;
  const settingsCount = entries.filter((entry) => entry.action === "config_update" || entry.action.startsWith("update_")).length;

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
          <p className="font-display text-xl font-semibold">No dashboard activity yet.</p>
          <p className="mt-2 text-sm text-ink-muted">
            Run a quick action or change a setting and the event will appear here automatically.
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
          {entries.map((entry, i) => (
            <ActivityRow key={`${entry.created_at}-${i}`} entry={entry} />
          ))}
        </ul>
      )}
    </main>
  );
}
