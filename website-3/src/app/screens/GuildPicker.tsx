import { Link } from "@tanstack/react-router";
import { inviteUrl } from "../../lib/api/client";
import type { Guild } from "../../lib/api/schemas";
import { useGuilds } from "../queries";

function GuildIcon({ guild }: { guild: Guild }) {
  if (guild.icon) {
    return (
      <img
        src={`https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64`}
        alt=""
        className="h-10 w-10 rounded-full border border-line"
      />
    );
  }
  return (
    <span className="font-display flex h-10 w-10 items-center justify-center rounded-full border border-line text-lg">
      {guild.name.charAt(0).toUpperCase()}
    </span>
  );
}

export default function GuildPicker() {
  const guilds = useGuilds();

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
          Could not load your servers.{" "}
          <button onClick={() => void guilds.refetch()} className="underline hover:text-ink">
            Try again
          </button>
        </p>
      )}

      {guilds.data && guilds.data.guilds.length === 0 && (
        <p className="mt-10 border-t border-line pt-6 text-sm text-ink-muted">
          No servers where you can Manage Server.
        </p>
      )}

      {guilds.data && guilds.data.guilds.length > 0 && (
        <ul className="mt-10">
          {guilds.data.guilds.map((g) => (
            <li
              key={g.id}
              className="flex items-center justify-between gap-4 border-t border-line py-5"
            >
              <div className="flex min-w-0 items-center gap-4">
                <GuildIcon guild={g} />
                <div className="min-w-0">
                  <p className="truncate font-medium">{g.name}</p>
                  {g.owner && (
                    <p className="text-xs tracking-[0.15em] text-ink-muted uppercase">Owner</p>
                  )}
                </div>
              </div>
              {g.bot_present ? (
                <Link
                  to="/g/$guildId"
                  params={{ guildId: g.id }}
                  className="shrink-0 rounded-full border border-line px-4 py-1.5 text-sm transition-colors hover:border-ink"
                >
                  Configure →
                </Link>
              ) : (
                <a
                  href={inviteUrl()}
                  className="shrink-0 text-sm text-ink-muted underline-offset-2 hover:underline"
                >
                  Invite the bot
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
