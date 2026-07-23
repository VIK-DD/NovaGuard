import { Link } from "@tanstack/react-router";
import { inviteUrl } from "../../lib/api/client";
import type { Guild } from "../../lib/api/schemas";
import { useGuilds } from "../queries";

function GuildIcon({ guild, muted = false }: { guild: Guild; muted?: boolean }) {
  if (guild.icon) {
    return (
      <img
        src={`https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64`}
        alt=""
        className={`h-10 w-10 rounded-full border border-line ${muted ? "opacity-70" : ""}`}
      />
    );
  }
  return (
    <span
      className={`font-display flex h-10 w-10 items-center justify-center rounded-full border border-line text-lg ${muted ? "text-ink-muted" : ""}`}
    >
      {guild.name.charAt(0).toUpperCase()}
    </span>
  );
}

export default function GuildPicker() {
  const guilds = useGuilds();
  const all = guilds.data?.guilds ?? [];
  const active = all.filter((g) => g.bot_present);
  const invitable = all.filter((g) => !g.bot_present);

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">Your servers</p>
      <h1 className="font-display mt-3 text-4xl">Pick a server to configure.</h1>

      {guilds.isPending && (
        <div className="mt-10" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse border-t border-line py-5">
              <div className="h-10 w-1/2 rounded bg-line/60" />
            </div>
          ))}
        </div>
      )}

      {guilds.isError && (
        <p className="mt-10 border-t border-line pt-6 text-sm text-ink-muted">
          We couldn't load your servers.{" "}
          <button onClick={() => void guilds.refetch()} className="underline hover:text-ink">
            Try again
          </button>
        </p>
      )}

      {guilds.data && all.length === 0 && (
        <p className="mt-10 border-t border-line pt-6 text-sm text-ink-muted">
          You don't manage any servers yet. NovaGuard only shows servers where you have Manage
          Server.
        </p>
      )}

      {active.length > 0 && (
        <ul className="mt-10 divide-y divide-line border-t border-line">
          {active.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-4 py-5">
              <div className="flex min-w-0 items-center gap-4">
                <GuildIcon guild={g} />
                <div className="min-w-0">
                  <p className="truncate font-medium">{g.name}</p>
                  {g.owner && (
                    <p className="text-xs tracking-[0.15em] text-ink-muted uppercase">Owner</p>
                  )}
                </div>
              </div>
              <Link
                to="/g/$guildId"
                params={{ guildId: g.id }}
                className="shrink-0 rounded-full border border-line-strong px-4 py-1.5 text-sm font-medium transition-colors hover:border-ink hover:bg-card"
              >
                Configure
              </Link>
            </li>
          ))}
        </ul>
      )}

      {invitable.length > 0 && (
        <section className="mt-14">
          <p className="text-xs tracking-[0.2em] text-ink-faint uppercase">Not set up yet</p>
          <p className="mt-1.5 text-sm text-ink-muted">
            {active.length > 0
              ? "NovaGuard isn't in these servers. Add it to start configuring."
              : "NovaGuard isn't in any of your servers yet. Add it to start configuring."}
          </p>
          <ul className="mt-5 divide-y divide-line border-t border-line">
            {invitable.map((g) => (
              <li key={g.id} className="flex items-center justify-between gap-4 py-5">
                <div className="flex min-w-0 items-center gap-4">
                  <GuildIcon guild={g} muted />
                  <div className="min-w-0">
                    <p className="truncate font-medium text-ink-muted">{g.name}</p>
                    {g.owner && (
                      <p className="text-xs tracking-[0.15em] text-ink-faint uppercase">Owner</p>
                    )}
                  </div>
                </div>
                <a
                  href={inviteUrl()}
                  className="shrink-0 rounded-full px-4 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary-soft"
                >
                  Add NovaGuard
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
