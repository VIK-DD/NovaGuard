import { Link, useParams } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { ApiError } from "../../lib/api/client";
import type { Dashboard } from "../../lib/api/schemas";
import Icon from "../components/Icon";
import { useGuildDashboard } from "../queries/guilds";

const timeFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZone: "Europe/Bucharest",
});

function compactNumber(value: number) {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function duration(seconds: number) {
  const total = Math.max(Math.floor(seconds || 0), 0);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return `${total}s`;
}

function pct(done: number, total: number) {
  return total > 0 ? Math.round((done / total) * 100) : 0;
}

function Card(props: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-card p-4 shadow-[0_1px_0_hsl(0_0%_100%/0.03)_inset] sm:p-5">
      <div className="flex items-start justify-between gap-4">
        <h2 className="font-display text-base font-semibold">{props.title}</h2>
        {props.action}
      </div>
      <div className="mt-4">{props.children}</div>
    </section>
  );
}

function Pill({ tone, children }: { tone: "good" | "warn" | "muted"; children: ReactNode }) {
  const cls =
    tone === "good"
      ? "border-good/35 bg-good/10 text-good"
      : tone === "warn"
        ? "border-primary/35 bg-primary-soft text-primary"
        : "border-line bg-bg-subtle text-ink-muted";
  return <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}>{children}</span>;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-card px-4 py-3">
      <p className="text-xs tracking-[0.16em] text-ink-muted uppercase">{label}</p>
      <p className="font-display mt-2 text-2xl font-semibold tracking-tight">{value}</p>
      {sub && <p className="mt-1 text-xs text-ink-muted">{sub}</p>}
    </div>
  );
}

function ToggleRow({ label, enabled }: { label: string; enabled: boolean }) {
  return (
    <div className="flex items-center justify-between border-t border-line py-3 first:border-t-0">
      <span className="text-sm">{label}</span>
      <span
        aria-hidden="true"
        className={`relative h-5 w-9 rounded-full border transition-colors ${
          enabled ? "border-primary bg-primary" : "border-line-strong bg-bg-subtle"
        }`}
      >
        <span
          className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow-sm transition-transform ${
            enabled ? "translate-x-[18px]" : "translate-x-[2px]"
          }`}
        />
      </span>
    </div>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-bg-subtle">
      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(Math.max(value, 0), 100)}%` }} />
    </div>
  );
}

function GuildHero({ data }: { data: Dashboard }) {
  const setupPercent = pct(data.setup.recommended_done, data.setup.recommended_total);
  return (
    <section className="border-b border-line bg-bg-subtle/55">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[1fr_22rem] lg:py-10">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            {data.guild.icon ? (
              <img src={data.guild.icon} alt="" className="h-12 w-12 rounded-full border border-line" />
            ) : (
              <span className="font-display grid h-12 w-12 place-items-center rounded-full border border-line text-lg">
                {data.guild.name.charAt(0).toUpperCase()}
              </span>
            )}
            <div className="min-w-0">
              <p className="text-xs tracking-[0.2em] text-primary uppercase">Control center</p>
              <h1 className="font-display truncate text-3xl font-semibold tracking-tight sm:text-4xl">
                {data.guild.name}
              </h1>
            </div>
          </div>
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Members" value={compactNumber(data.guild.member_count)} />
            <Stat label="Commands" value={String(data.status.commands)} />
            <Stat label="Uptime" value={duration(data.status.uptime_seconds)} />
            <Stat label="Tracked XP" value={compactNumber(data.levels.tracked_members)} />
          </div>
        </div>
        <Card title="System">
          <div className="flex items-center justify-between gap-3">
            <Pill tone={data.status.ready ? "good" : "warn"}>
              {data.status.ready ? "Online" : "Starting"}
            </Pill>
            <span className="text-sm text-ink-muted">
              v{data.status.version} "{data.status.codename}"
            </span>
          </div>
          <div className="mt-5">
            <div className="mb-2 flex items-center justify-between text-xs text-ink-muted">
              <span>Recommended setup</span>
              <span>{setupPercent}%</span>
            </div>
            <Progress value={setupPercent} />
            <p className="mt-2 text-xs text-ink-muted">
              {data.setup.recommended_done}/{data.setup.recommended_total} recommended items complete.
            </p>
          </div>
        </Card>
      </div>
    </section>
  );
}

export default function GuildOverview() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const dashboard = useGuildDashboard(guildId);

  if (dashboard.isPending) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6" aria-busy="true">
        <div className="h-32 animate-pulse rounded-[var(--radius-card)] bg-line/50" />
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-44 animate-pulse rounded-[var(--radius-card)] bg-line/40" />
          ))}
        </div>
      </main>
    );
  }

  if (dashboard.isError || !dashboard.data) {
    const code = dashboard.error instanceof ApiError ? dashboard.error.code : "internal_error";
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16">
        <h1 className="font-display text-3xl">
          {code === "forbidden" ? "You need Manage Server here." : "Could not load this dashboard."}
        </h1>
        <button
          onClick={() => void dashboard.refetch()}
          className="ng-touch-target mt-6 inline-flex items-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-ink"
        >
          Retry
        </button>
      </main>
    );
  }

  const data = dashboard.data;
  const backupTone = data.backup.ok ? "good" : data.backup.available ? "warn" : "muted";

  return (
    <>
      <GuildHero data={data} />
      <main className="mx-auto max-w-6xl px-4 py-6 pb-24 sm:px-6">
        <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
          <Card
            title="Modules"
            action={
              <Link to="/g/$guildId/settings" params={{ guildId }} className="text-sm text-primary hover:underline">
                Edit settings
              </Link>
            }
          >
            <div className="grid gap-x-6 sm:grid-cols-2">
              {data.modules.map((module) => (
                <ToggleRow key={module.key} label={module.label} enabled={module.enabled} />
              ))}
            </div>
            <div className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-3">
              <Pill tone={data.automod.invites ? "good" : "muted"}>Invites {data.automod.invites ? "blocked" : "open"}</Pill>
              <Pill tone={data.automod.spam ? "good" : "muted"}>Anti-spam {data.automod.spam ? "on" : "off"}</Pill>
              <Pill tone={data.automod.badwords_count ? "good" : "muted"}>
                {data.automod.badwords_count} blocked words
              </Pill>
            </div>
          </Card>

          <Card
            title="Backup health"
            action={<Pill tone={backupTone}>{data.backup.ok ? "Verified" : data.backup.available ? "Check" : "Empty"}</Pill>}
          >
            {data.backup.available ? (
              <div>
                <p className="break-all text-sm font-medium">{data.backup.latest_name}</p>
                <p className="mt-1 text-sm text-ink-muted">
                  {data.backup.latest_size_text} - {data.backup.latest_at ? timeFmt.format(new Date(data.backup.latest_at)) : "unknown"}
                </p>
                {(data.backup.errors.length > 0 || data.backup.warnings.length > 0) && (
                  <p className="mt-3 text-sm text-primary">
                    {[...data.backup.errors, ...data.backup.warnings][0]}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-ink-muted">No backup archive has been created yet.</p>
            )}
            <p className="mt-4 text-xs text-ink-muted">Use `/backup test` in Discord for a restore check.</p>
          </Card>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Card title="Levels leaderboard">
            {data.levels.leaderboard.length ? (
              <ol className="divide-y divide-line">
                {data.levels.leaderboard.map((row) => (
                  <li key={row.user_id} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        #{row.position} {row.display_name}
                      </p>
                      <p className="text-xs text-ink-muted">Level {row.level} - {row.messages.toLocaleString("en")} messages</p>
                    </div>
                    <span className="shrink-0 text-sm text-primary">{row.xp.toLocaleString("en")} XP</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-ink-muted">No XP records yet.</p>
            )}
          </Card>

          <Card title="Voice reports">
            <div className="mb-3 flex items-center gap-2">
              <Pill tone={data.voice.configured ? "good" : "muted"}>
                {data.voice.configured ? "Configured" : "Off"}
              </Pill>
              {data.voice.pending_count > 0 && <Pill tone="warn">{data.voice.pending_count} pending</Pill>}
            </div>
            {data.voice.recent_reports.length ? (
              <ul className="divide-y divide-line">
                {data.voice.recent_reports.map((report) => (
                  <li key={report.id} className="py-3 first:pt-0 last:pb-0">
                    <p className="truncate text-sm font-medium">{report.channel_name}</p>
                    <p className="text-xs text-ink-muted">
                      {duration(report.duration_seconds)} - {report.unique_members} people - peak {report.peak_members}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-ink-muted">No saved voice reports yet.</p>
            )}
          </Card>

          <Card
            title="Recent changes"
            action={
              <Link to="/g/$guildId/audit" params={{ guildId }} className="text-sm text-primary hover:underline">
                Audit
              </Link>
            }
          >
            {data.updates.length ? (
              <ul className="divide-y divide-line">
                {data.updates.slice(0, 4).map((update, index) => (
                  <li key={`${update.created_at}-${index}`} className="py-3 first:pt-0 last:pb-0">
                    <p className="text-sm font-medium">
                      Update {update.build ? `#${update.build}` : ""}
                    </p>
                    <p className="line-clamp-2 text-xs text-ink-muted">
                      {(update.highlights?.[0] || update.changes?.[0] || "Internal improvements").replace(/\s+/g, " ")}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-ink-muted">No updates published yet.</p>
            )}
          </Card>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Link
            to="/g/$guildId/settings"
            params={{ guildId }}
            className="ng-pressable flex min-h-12 items-center justify-between rounded-[var(--radius-card)] border border-line bg-card px-4 text-sm hover:border-line-strong"
          >
            Configure server <Icon name="shield-check" size={18} />
          </Link>
          <Link
            to="/g/$guildId/audit"
            params={{ guildId }}
            className="ng-pressable flex min-h-12 items-center justify-between rounded-[var(--radius-card)] border border-line bg-card px-4 text-sm hover:border-line-strong"
          >
            Review audit log <Icon name="hash" size={18} />
          </Link>
          <button
            type="button"
            onClick={() => void dashboard.refetch()}
            className="ng-pressable flex min-h-12 items-center justify-between rounded-[var(--radius-card)] border border-line bg-card px-4 text-left text-sm hover:border-line-strong"
          >
            Refresh dashboard <Icon name="list" size={18} flat />
          </button>
        </div>
      </main>
    </>
  );
}
