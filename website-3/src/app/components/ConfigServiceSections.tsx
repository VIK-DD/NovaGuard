import { useCallback } from "react";
import type {
  AiSettings,
  GuildChannel,
  GuildConfig,
  GuildSettings,
} from "../../lib/api/schemas";
import { isModuleActive } from "../moduleCatalog";
import ChannelSelect from "./ChannelSelect";
import { NumberField, Section, Toggle } from "./ConfigPrimitives";

type FieldErrors = Record<string, string>;

interface AiSectionProps {
  settings: GuildSettings;
  status: GuildConfig["ai_status"];
  channels: GuildChannel[];
  fieldErrors: FieldErrors;
  onEnabledChange: (value: boolean) => void;
  onChannelChange: (value: string | null) => void;
  onAnswerModeChange: (value: AiSettings["answer_mode"]) => void;
  onQuestionLimitChange: (value: number) => void;
}

export function AiSection(props: AiSectionProps) {
  const { ai } = props.settings;
  return (
    <Section
      id="ai"
      icon="hash"
      kicker="AI assistant"
      description="Control how /ask uses the optional Claude integration on this server."
      active={isModuleActive(props.settings, "ai")}
    >
      <div className={`border-t py-5 ${props.status.available ? "border-line" : "border-primary/40"}`}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium">
              {props.status.available
                ? "Claude is available"
                : "Claude is not configured on the bot host"}
            </p>
            <p className="mt-1 text-xs leading-5 text-ink-muted">
              {props.status.available
                ? `${props.status.model} · ${props.status.daily_calls}/${props.status.daily_cap} calls used today`
                : "Add ANTHROPIC_API_KEY to the Oracle .env file and restart PM2. The key is never returned to this dashboard."}
            </p>
          </div>
          <span
            className={`w-fit rounded-full border px-3 py-1 text-xs ${
              props.status.available
                ? "border-good/40 text-good"
                : "border-primary/40 text-primary"
            }`}
          >
            {props.status.available ? "Provider ready" : "Host setup needed"}
          </span>
        </div>
        {props.status.available && (
          <p className="mt-3 text-xs text-ink-faint">
            Current minute: {props.status.minute_calls}/{props.status.minute_cap} requests. Limits
            are global cost guards for every server using this bot instance.
          </p>
        )}
      </div>

      <Toggle
        label="Enable /ask on this server"
        checked={ai.enabled}
        onChange={props.onEnabledChange}
      />

      <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <ChannelSelect
          label="Only allow /ask in"
          value={ai.channel_id}
          channels={props.channels}
          error={props.fieldErrors["ai.channel_id"]}
          onChange={props.onChannelChange}
        />
        <label className="block">
          <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
            Answer visibility
          </span>
          <select
            value={ai.answer_mode}
            onChange={(event) =>
              props.onAnswerModeChange(event.target.value as AiSettings["answer_mode"])
            }
            aria-invalid={props.fieldErrors["ai.answer_mode"] ? true : undefined}
            className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
              props.fieldErrors["ai.answer_mode"] ? "border-primary" : "border-line"
            }`}
          >
            <option value="public">Public in the channel</option>
            <option value="private">Private to the person asking</option>
          </select>
          {props.fieldErrors["ai.answer_mode"] && (
            <p className="mt-1 text-xs text-primary">{props.fieldErrors["ai.answer_mode"]}</p>
          )}
        </label>
        <NumberField
          label="Maximum question length"
          value={ai.max_question_chars}
          min={100}
          max={2000}
          suffix="chars"
          error={props.fieldErrors["ai.max_question_chars"]}
          onChange={props.onQuestionLimitChange}
        />
      </div>
      <p className="mt-4 text-xs leading-5 text-ink-muted">
        Leaving the channel empty allows <code>/ask</code> everywhere. Questions are sent to
        Anthropic only when a member runs the command; NovaGuard does not store a local question
        history.
      </p>
    </Section>
  );
}

interface EconomySectionProps {
  settings: GuildSettings;
  status: GuildConfig["economy_status"];
  fieldErrors: FieldErrors;
  onChange: (patch: Partial<GuildSettings["economy"]>) => void;
}

export function EconomySection(props: EconomySectionProps) {
  const { economy } = props.settings;
  const onEnabledChange = useCallback(
    (value: boolean) => props.onChange({ enabled: value }),
    [props.onChange],
  );
  const onDailyBaseChange = useCallback(
    (value: number) => props.onChange({ daily_base: value }),
    [props.onChange],
  );
  const onDailyStreakBonusChange = useCallback(
    (value: number) => props.onChange({ daily_streak_bonus: value }),
    [props.onChange],
  );
  const onWorkMinChange = useCallback(
    (value: number) => props.onChange({ work_min: value }),
    [props.onChange],
  );
  const onWorkMaxChange = useCallback(
    (value: number) => props.onChange({ work_max: value }),
    [props.onChange],
  );
  const onWorkCooldownChange = useCallback(
    (value: number) => props.onChange({ work_cooldown_minutes: value }),
    [props.onChange],
  );
  const onTransfersChange = useCallback(
    (value: boolean) => props.onChange({ transfers_enabled: value }),
    [props.onChange],
  );
  const onGamesChange = useCallback(
    (value: boolean) => props.onChange({ games_enabled: value }),
    [props.onChange],
  );
  const onShopChange = useCallback(
    (value: boolean) => props.onChange({ shop_enabled: value }),
    [props.onChange],
  );
  const onGambleMaxChange = useCallback(
    (value: number) => props.onChange({ gamble_max_bet: value }),
    [props.onChange],
  );
  const onSlotsMaxChange = useCallback(
    (value: number) => props.onChange({ slots_max_bet: value }),
    [props.onChange],
  );

  return (
    <Section
      id="economy"
      icon="trophy"
      kicker="Economy"
      description="Tune earning rules and optional features without editing wallet balances."
      active={isModuleActive(props.settings, "economy")}
    >
      <div className="grid gap-4 border-t border-line py-5 sm:grid-cols-3">
        <div>
          <p className="text-xs tracking-[0.15em] text-ink-muted uppercase">Wallets</p>
          <p className="font-display mt-1 text-2xl">
            {props.status.tracked_wallets.toLocaleString("en")}
          </p>
        </div>
        <div>
          <p className="text-xs tracking-[0.15em] text-ink-muted uppercase">
            Coins in circulation
          </p>
          <p className="font-display mt-1 text-2xl">
            {props.status.total_coins.toLocaleString("en")}
          </p>
        </div>
        <div>
          <p className="text-xs tracking-[0.15em] text-ink-muted uppercase">Shop items</p>
          <p className="font-display mt-1 text-2xl">{props.status.shop.length}</p>
        </div>
      </div>

      <Toggle
        label="Enable the economy on this server"
        checked={economy.enabled}
        onChange={onEnabledChange}
      />

      <div className="mt-6">
        <p className="text-sm font-medium">Daily rewards</p>
        <div className="mt-3 grid gap-5 sm:grid-cols-2">
          <NumberField
            label="Base daily reward"
            value={economy.daily_base}
            min={0}
            max={100000}
            suffix="coins"
            error={props.fieldErrors["economy.daily_base"]}
            onChange={onDailyBaseChange}
          />
          <NumberField
            label="Streak bonus per day"
            value={economy.daily_streak_bonus}
            min={0}
            max={10000}
            suffix="coins"
            error={props.fieldErrors["economy.daily_streak_bonus"]}
            onChange={onDailyStreakBonusChange}
          />
        </div>
        <p className="mt-2 text-xs leading-5 text-ink-muted">
          The streak bonus grows for at most ten bonus days, matching the live `/daily` logic.
        </p>
      </div>

      <div className="mt-7 border-t border-line pt-5">
        <p className="text-sm font-medium">Work rewards</p>
        <div className="mt-3 grid gap-5 sm:grid-cols-3">
          <NumberField
            label="Minimum"
            value={economy.work_min}
            min={0}
            max={100000}
            suffix="coins"
            error={props.fieldErrors["economy.work_min"]}
            onChange={onWorkMinChange}
          />
          <NumberField
            label="Maximum"
            value={economy.work_max}
            min={0}
            max={100000}
            suffix="coins"
            error={props.fieldErrors["economy.work_max"]}
            onChange={onWorkMaxChange}
          />
          <NumberField
            label="Cooldown"
            value={economy.work_cooldown_minutes}
            min={1}
            max={1440}
            suffix="min"
            error={props.fieldErrors["economy.work_cooldown_minutes"]}
            onChange={onWorkCooldownChange}
          />
        </div>
      </div>

      <div className="mt-7 border-t border-line pt-2">
        <Toggle
          label="Allow member-to-member transfers"
          checked={economy.transfers_enabled}
          onChange={onTransfersChange}
        />
        <Toggle
          label="Enable gamble and slots"
          checked={economy.games_enabled}
          onChange={onGamesChange}
        />
        <Toggle
          label="Enable shop purchases and crates"
          checked={economy.shop_enabled}
          onChange={onShopChange}
        />
      </div>

      <div className="mt-6 grid gap-5 sm:grid-cols-2">
        <NumberField
          label="Maximum /gamble bet"
          value={economy.gamble_max_bet}
          min={10}
          max={1000000}
          suffix="coins"
          error={props.fieldErrors["economy.gamble_max_bet"]}
          onChange={onGambleMaxChange}
        />
        <NumberField
          label="Maximum /slots bet"
          value={economy.slots_max_bet}
          min={10}
          max={100000}
          suffix="coins"
          error={props.fieldErrors["economy.slots_max_bet"]}
          onChange={onSlotsMaxChange}
        />
      </div>

      <div className="mt-8 grid gap-7 border-t border-line pt-6 lg:grid-cols-2">
        <div>
          <p className="text-sm font-medium">Richest members</p>
          {props.status.leaderboard.length > 0 ? (
            <ol className="mt-3 divide-y divide-line border-y border-line">
              {props.status.leaderboard.slice(0, 5).map((member) => (
                <li
                  key={member.user_id}
                  className="flex items-center justify-between gap-3 py-3 text-sm"
                >
                  <span className="min-w-0 truncate">
                    <span className="mr-2 text-ink-faint">#{member.position}</span>
                    {member.display_name}
                  </span>
                  <span className="shrink-0 text-ink-muted">
                    🪙 {member.coins.toLocaleString("en")}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="mt-3 text-sm text-ink-muted">No funded wallets yet.</p>
          )}
        </div>
        <div>
          <p className="text-sm font-medium">Shop catalogue</p>
          <ul className="mt-3 divide-y divide-line border-y border-line">
            {props.status.shop.map((item) => (
              <li
                key={item.key}
                className="flex items-center justify-between gap-3 py-3 text-sm"
              >
                <span className="min-w-0 truncate">
                  {item.icon} {item.label}
                </span>
                <span className="shrink-0 text-ink-muted">
                  🪙 {item.price.toLocaleString("en")}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs leading-5 text-ink-muted">
            Shop prices are global product rules; this page controls access without silently
            changing the value of items members already bought.
          </p>
        </div>
      </div>
    </Section>
  );
}
