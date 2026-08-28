import type { GuildChannel, GuildConfig, GuildSettings } from "../../lib/api/schemas";
import { isModuleActive } from "../moduleCatalog";
import ChannelSelect from "./ChannelSelect";
import { Section } from "./ConfigPrimitives";

interface GiveawaySectionProps {
  guildId: string;
  settings: GuildSettings;
  giveaways: GuildConfig["giveaways"];
  channels: GuildChannel[];
  fieldErrors: Record<string, string>;
  dirty: boolean;
  prize: string;
  duration: string;
  winners: number;
  notice: string | null;
  confirmEndId: string | null;
  startPending: boolean;
  startError: boolean;
  managePending: boolean;
  manageError: boolean;
  managingMessageId: string | null;
  onChannelChange: (value: string | null) => void;
  onPrizeChange: (value: string) => void;
  onDurationChange: (value: string) => void;
  onWinnersChange: (value: number) => void;
  onStart: () => void;
  onConfirmEndChange: (messageId: string | null) => void;
  onEnd: (messageId: string) => void;
  onReroll: (messageId: string) => void;
}

export function GiveawaySection(props: GiveawaySectionProps) {
  const active = props.giveaways.filter((giveaway) => !giveaway.ended);
  const completed = props.giveaways.filter((giveaway) => giveaway.ended);

  return (
    <Section
      id="giveaways"
      icon="trophy"
      kicker="Giveaways"
      description="Create timed draws, watch entry counts and manage results from one place."
      active={isModuleActive(props.settings, "giveaways")}
    >
      <div className="max-w-md border-t border-line pt-6">
        <ChannelSelect
          label="Giveaway channel"
          value={props.settings.giveaway_channel}
          channels={props.channels}
          error={props.fieldErrors.giveaway_channel}
          onChange={props.onChannelChange}
        />
      </div>

      <div className="mt-7 rounded-lg border border-line bg-bg-subtle p-4 sm:p-5">
        <p className="text-sm font-medium">Start a giveaway</p>
        <p className="mt-1 text-xs leading-5 text-ink-muted">
          Durations accept combinations such as 30m, 1h 30m or 2d, from one minute to 30 days.
        </p>
        <div className="mt-5 grid gap-5 sm:grid-cols-[minmax(0,1fr)_9rem_8rem]">
          <label className="block">
            <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">Prize</span>
            <input
              value={props.prize}
              maxLength={200}
              onChange={(event) => props.onPrizeChange(event.target.value)}
              placeholder="One month of Nitro"
              className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
            />
          </label>
          <label className="block">
            <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">Duration</span>
            <input
              value={props.duration}
              maxLength={40}
              onChange={(event) => props.onDurationChange(event.target.value)}
              placeholder="1d"
              className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
            />
          </label>
          <label className="block">
            <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">Winners</span>
            <input
              type="number"
              min={1}
              max={10}
              step={1}
              value={props.winners}
              onChange={(event) => props.onWinnersChange(Number(event.target.value))}
              className="mt-1.5 w-full rounded-md border border-line bg-card px-3 py-2 text-sm outline-none focus:border-ink"
            />
          </label>
        </div>
        <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs leading-5 text-ink-muted">
            {props.dirty
              ? "Save the channel change before starting."
              : "The draw closes automatically and announces winners in this channel."}
          </p>
          <button
            type="button"
            disabled={
              props.dirty ||
              !props.settings.giveaway_channel ||
              !props.prize.trim() ||
              !props.duration.trim() ||
              !Number.isInteger(props.winners) ||
              props.winners < 1 ||
              props.winners > 10 ||
              props.startPending
            }
            onClick={props.onStart}
            className="ng-touch-target inline-flex shrink-0 items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {props.startPending ? "Starting…" : "Start giveaway"}
          </button>
        </div>
        {props.notice && (
          <p
            role={props.startError || props.manageError ? "alert" : "status"}
            className={`mt-3 border-t border-line pt-3 text-sm ${
              props.startError || props.manageError ? "text-primary" : "text-good"
            }`}
          >
            {props.notice}
          </p>
        )}
      </div>

      <div className="mt-7 border-t border-line pt-5">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-medium">Active giveaways</p>
          <span className="rounded-full border border-line bg-bg-subtle px-2.5 py-1 text-xs text-ink-muted">
            {active.length}
          </span>
        </div>
        {active.length > 0 ? (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {active.map((giveaway) => {
              const channel = props.channels.find((item) => item.id === giveaway.channel_id);
              const isPending =
                props.managePending && props.managingMessageId === giveaway.message_id;
              const isConfirming = props.confirmEndId === giveaway.message_id;
              return (
                <li
                  key={giveaway.message_id}
                  className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-ink">{giveaway.prize}</span>
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      #{channel?.name ?? "deleted-channel"} · {giveaway.entrant_count} entries · ends{" "}
                      {new Date(giveaway.ends_at).toLocaleString("en-US")}
                    </span>
                  </span>
                  <span className="flex shrink-0 flex-wrap items-center gap-2">
                    <a
                      href={`https://discord.com/channels/${props.guildId}/${giveaway.channel_id}/${giveaway.message_id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-primary hover:underline"
                    >
                      Open ↗
                    </a>
                    {isConfirming ? (
                      <>
                        <button
                          type="button"
                          disabled={isPending}
                          onClick={() => props.onConfirmEndChange(null)}
                          className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-ink"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          disabled={isPending}
                          onClick={() => props.onEnd(giveaway.message_id)}
                          className="ng-touch-target inline-flex items-center rounded-full border border-primary px-4 py-2 text-sm text-primary disabled:opacity-45"
                        >
                          {isPending ? "Ending…" : "Confirm end"}
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        onClick={() => props.onConfirmEndChange(giveaway.message_id)}
                        className="ng-touch-target inline-flex items-center rounded-md px-2 text-sm text-ink-muted hover:text-primary"
                      >
                        End early
                      </button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-ink-muted">No giveaways are active.</p>
        )}
      </div>

      <div className="mt-7 border-t border-line pt-5">
        <p className="text-sm font-medium">Recent results</p>
        {completed.length > 0 ? (
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {completed.map((giveaway) => {
              const isPending =
                props.managePending && props.managingMessageId === giveaway.message_id;
              return (
                <li
                  key={giveaway.message_id}
                  className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-ink">{giveaway.prize}</span>
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      {giveaway.entrant_count} entries · {giveaway.winner_ids.length} recorded winner
                      {giveaway.winner_ids.length === 1 ? "" : "s"}
                    </span>
                  </span>
                  <button
                    type="button"
                    disabled={giveaway.entrant_count === 0 || isPending}
                    onClick={() => props.onReroll(giveaway.message_id)}
                    className="ng-touch-target inline-flex shrink-0 items-center rounded-full border border-line px-4 py-2 text-sm transition-colors hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {isPending ? "Rerolling…" : "Reroll"}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-ink-muted">No completed giveaways yet.</p>
        )}
      </div>
    </Section>
  );
}
