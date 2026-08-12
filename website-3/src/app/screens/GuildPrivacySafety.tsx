import { Link, useParams } from "@tanstack/react-router";
import { ApiError } from "../../lib/api/client";
import Icon from "../components/Icon";
import { getPrivacySafetySignals } from "../lib/privacySafety";
import { useGuildConfig } from "../queries/guilds";

function StatePill({ active, label }: { active: boolean; label: string }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${
        active
          ? "border-primary/35 bg-primary-soft text-primary"
          : "border-line bg-bg-subtle text-ink-muted"
      }`}
    >
      {active ? label : "Off"}
    </span>
  );
}

export default function GuildPrivacySafety() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const config = useGuildConfig(guildId);

  if (config.isPending) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6" aria-busy="true">
        <div className="h-40 animate-pulse rounded-[var(--radius-card)] bg-line/50" />
      </main>
    );
  }

  if (config.isError || !config.data) {
    const code = config.error instanceof ApiError ? config.error.code : "internal_error";
    return (
      <main className="mx-auto max-w-3xl px-4 py-10 sm:px-6 sm:py-16">
        <p className="text-xs tracking-[0.2em] text-primary uppercase">Privacy &amp; safety</p>
        <h1 className="font-display mt-3 text-3xl font-semibold tracking-tight">
          Could not load this server's settings.
        </h1>
        <p className="mt-3 max-w-lg text-sm leading-6 text-ink-muted">
          {code === "forbidden"
            ? "You need Manage Server permission to review this server."
            : "Check the connection and try again."}
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          {code !== "forbidden" && (
            <button
              type="button"
              onClick={() => void config.refetch()}
              className="ng-touch-target inline-flex items-center rounded-full bg-primary px-5 py-2 text-sm text-primary-ink transition-opacity hover:opacity-90"
            >
              Try again
            </button>
          )}
          <Link
            to="/g/$guildId"
            params={{ guildId }}
            className="ng-touch-target inline-flex items-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-ink"
          >
            Back to overview
          </Link>
        </div>
      </main>
    );
  }

  const signals = getPrivacySafetySignals(config.data.settings);
  const activeSignals = signals.filter((signal) => signal.active);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 pb-24 sm:px-6 sm:py-10">
      <section className="rounded-[var(--radius-card)] border border-line bg-bg-subtle/55 p-5 sm:p-7">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-2xl">
            <p className="text-xs tracking-[0.2em] text-primary uppercase">Privacy &amp; safety</p>
            <h1 className="font-display mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              {config.data.guild.name}
            </h1>
            <p className="mt-3 text-sm leading-6 text-ink-muted">
              This summary reads the features configured in this server and highlights the
              member-facing effects worth explaining. It cannot verify whether your community
              notice has been posted, so keep that as a human check.
            </p>
          </div>
          <div className="rounded-[var(--radius-card)] border border-line bg-card px-4 py-3 sm:min-w-44">
            <p className="text-xs tracking-[0.16em] text-ink-muted uppercase">Review now</p>
            <p className="font-display mt-1 text-2xl font-semibold text-primary">
              {activeSignals.length}
            </p>
            <p className="text-xs text-ink-muted">
              {activeSignals.length === 1 ? "active feature effect" : "active feature effects"}
            </p>
          </div>
        </div>
      </section>

      <section className="mt-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs tracking-[0.2em] text-primary uppercase">Configuration review</p>
            <h2 className="font-display mt-2 text-2xl font-semibold tracking-tight">What members should know</h2>
          </div>
          <Link
            to="/g/$guildId/settings"
            params={{ guildId }}
            className="text-sm text-primary transition-colors hover:underline"
          >
            Manage modules
          </Link>
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {signals.map((signal) => (
            <article
              key={signal.moduleId}
              className="rounded-[var(--radius-card)] border border-line bg-card p-5 shadow-[0_1px_0_hsl(0_0%_100%/0.03)_inset]"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[8px] border border-line bg-bg-subtle text-ink">
                    <Icon
                      name={
                        signal.moduleId === "moderation"
                          ? "shield-check"
                          : signal.moduleId === "tickets"
                            ? "clipboard-text"
                            : signal.moduleId === "ai"
                              ? "hash"
                              : "users-three"
                      }
                      size={18}
                    />
                  </span>
                  <h3 className="pt-1 text-sm font-semibold">{signal.title}</h3>
                </div>
                <StatePill active={signal.active} label={signal.activeLabel} />
              </div>
              <p className="mt-4 min-h-15 text-sm leading-6 text-ink-muted">
                {signal.active ? signal.activeDetail : signal.inactiveDetail}
              </p>
              <Link
                to="/g/$guildId/settings/$moduleId"
                params={{ guildId, moduleId: signal.moduleId }}
                className="mt-4 inline-flex min-h-11 items-center text-sm text-primary transition-colors hover:underline"
              >
                Review {signal.title.toLowerCase()}
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-5 grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <article className="rounded-[var(--radius-card)] border border-line bg-card p-5 sm:p-6">
          <p className="text-xs tracking-[0.2em] text-primary uppercase">Member notice</p>
          <h2 className="font-display mt-2 text-2xl font-semibold tracking-tight">Make the active features understandable.</h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-ink-muted">
            Adapt NovaGuard's ready-to-paste notice to the functions above, then post it in your
            rules, onboarding or privacy channel. Include a moderator contact for community-specific
            questions and appeals.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <a
              href="/server-admin-notice"
              target="_blank"
              rel="noreferrer"
              className="ng-touch-target inline-flex items-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90"
            >
              Open copyable notice
            </a>
            <a
              href="/privacy"
              target="_blank"
              rel="noreferrer"
              className="ng-touch-target inline-flex items-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-line-strong"
            >
              Read Privacy Policy
            </a>
          </div>
        </article>

        <article className="rounded-[var(--radius-card)] border border-line bg-card p-5 sm:p-6">
          <p className="text-xs tracking-[0.2em] text-primary uppercase">Member controls</p>
          <h2 className="font-display mt-2 text-2xl font-semibold tracking-tight">Private data requests</h2>
          <dl className="mt-4 divide-y divide-line border-t border-line text-sm">
            <div className="grid gap-1 py-3 sm:grid-cols-[10rem_1fr] sm:gap-3">
              <dt><code>/privacy export</code></dt>
              <dd className="text-ink-muted">A member receives their NovaGuard records privately.</dd>
            </div>
            <div className="grid gap-1 py-3 sm:grid-cols-[10rem_1fr] sm:gap-3">
              <dt><code>/privacy delete</code></dt>
              <dd className="text-ink-muted">A member receives a final export and requests erasure.</dd>
            </div>
            <div className="grid gap-1 py-3 sm:grid-cols-[10rem_1fr] sm:gap-3">
              <dt><code>/privacy server-export</code></dt>
              <dd className="text-ink-muted">An administrator can privately export this server's records.</dd>
            </div>
          </dl>
        </article>
      </section>
    </main>
  );
}
