import type {
  AnnounceMode,
  GuildChannel,
  GuildRole,
  GuildSettings,
} from "../../lib/api/schemas";
import { isModuleActive } from "../moduleCatalog";
import BadwordsEditor from "./BadwordsEditor";
import ChannelSelect from "./ChannelSelect";
import { NumberField, Section, Toggle } from "./ConfigPrimitives";
import IgnoreListEditor from "./IgnoreListEditor";
import RoleSelect from "./RoleSelect";

type FieldErrors = Record<string, string>;
type ChannelChange = (value: string | null) => void;

interface WelcomeSectionProps {
  settings: GuildSettings;
  channels: GuildChannel[];
  roles: GuildRole[];
  fieldErrors: FieldErrors;
  onWelcomeChannelChange: ChannelChange;
  onGoodbyeChannelChange: ChannelChange;
  onAutoroleChange: ChannelChange;
}

export function WelcomeSection(props: WelcomeSectionProps) {
  return (
    <Section
      id="welcome"
      icon="users-three"
      kicker="Welcome"
      description="Greet new members, announce departures and assign a starter role."
      active={isModuleActive(props.settings, "welcome")}
    >
      <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <ChannelSelect
          label="Welcome channel"
          value={props.settings.welcome_channel}
          channels={props.channels}
          error={props.fieldErrors.welcome_channel}
          onChange={props.onWelcomeChannelChange}
        />
        <ChannelSelect
          label="Goodbye channel"
          value={props.settings.goodbye_channel}
          channels={props.channels}
          error={props.fieldErrors.goodbye_channel}
          onChange={props.onGoodbyeChannelChange}
        />
        <RoleSelect
          label="Auto-role for newcomers"
          value={props.settings.autorole}
          roles={props.roles.filter((role) => role.assignable)}
          error={props.fieldErrors.autorole}
          onChange={props.onAutoroleChange}
        />
      </div>
    </Section>
  );
}

interface ModerationSectionProps {
  settings: GuildSettings;
  channels: GuildChannel[];
  roles: GuildRole[];
  fieldErrors: FieldErrors;
  onLogChannelChange: ChannelChange;
  onErrorLogChannelChange: ChannelChange;
  onInvitesChange: (value: boolean) => void;
  onSpamChange: (value: boolean) => void;
  onBadwordsChange: (value: string[]) => void;
  onIgnoredChannelsChange: (value: string[]) => void;
  onIgnoredRolesChange: (value: string[]) => void;
  onSpamMessagesChange: (value: number) => void;
  onSpamWindowChange: (value: number) => void;
  onSpamTimeoutChange: (value: number) => void;
}

export function ModerationSection(props: ModerationSectionProps) {
  const { automod } = props.settings;
  return (
    <Section
      id="moderation"
      icon="shield-check"
      kicker="Moderation"
      description="Filter unwanted messages and keep staff-facing activity in the right channels."
      active={isModuleActive(props.settings, "moderation")}
    >
      <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <ChannelSelect
          label="Server log channel"
          value={props.settings.log_channel}
          channels={props.channels}
          error={props.fieldErrors.log_channel}
          onChange={props.onLogChannelChange}
        />
        <ChannelSelect
          label="Error log channel"
          value={props.settings.error_log_channel}
          channels={props.channels}
          error={props.fieldErrors.error_log_channel}
          onChange={props.onErrorLogChannelChange}
        />
      </div>
      <div className="mt-6 border-t border-line pt-2">
        <Toggle
          label="Block Discord invites"
          checked={automod.invites}
          onChange={props.onInvitesChange}
        />
        <Toggle label="Anti-spam" checked={automod.spam} onChange={props.onSpamChange} />
        <div className="border-t border-line pt-4">
          <BadwordsEditor
            value={automod.badwords}
            error={
              props.fieldErrors["automod.badwords"] ??
              props.fieldErrors.badwords ??
              props.fieldErrors.automod
            }
            onChange={props.onBadwordsChange}
          />
        </div>
        <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-3">
          <NumberField
            label="Messages"
            suffix="to trigger"
            value={automod.spam_messages}
            min={3}
            max={20}
            error={props.fieldErrors["automod.spam_messages"]}
            onChange={props.onSpamMessagesChange}
          />
          <NumberField
            label="Detection window"
            suffix="seconds"
            value={automod.spam_window_seconds}
            min={2}
            max={60}
            error={props.fieldErrors["automod.spam_window_seconds"]}
            onChange={props.onSpamWindowChange}
          />
          <NumberField
            label="Timeout"
            suffix="seconds"
            value={automod.spam_timeout_seconds}
            min={10}
            max={86400}
            error={props.fieldErrors["automod.spam_timeout_seconds"]}
            onChange={props.onSpamTimeoutChange}
          />
        </div>
        <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
          <IgnoreListEditor
            label="Channels exempt from AutoMod"
            prefix="#"
            value={automod.ignored_channels}
            options={props.channels}
            error={props.fieldErrors["automod.ignored_channels"]}
            onChange={props.onIgnoredChannelsChange}
          />
          <IgnoreListEditor
            label="Roles exempt from AutoMod"
            prefix="@"
            value={automod.ignored_roles}
            options={props.roles}
            error={props.fieldErrors["automod.ignored_roles"]}
            onChange={props.onIgnoredRolesChange}
          />
        </div>
      </div>
    </Section>
  );
}

interface LevelsSectionProps {
  settings: GuildSettings;
  channels: GuildChannel[];
  roles: GuildRole[];
  fieldErrors: FieldErrors;
  onEnabledChange: (value: boolean) => void;
  onAnnounceChange: (value: AnnounceMode) => void;
  onAnnounceChannelChange: ChannelChange;
  onXpMinChange: (value: number) => void;
  onXpMaxChange: (value: number) => void;
  onCooldownChange: (value: number) => void;
  onIgnoredChannelsChange: (value: string[]) => void;
  onIgnoredRolesChange: (value: string[]) => void;
}

export function LevelsSection(props: LevelsSectionProps) {
  const { levels } = props.settings;
  return (
    <Section
      id="levels"
      icon="trophy"
      kicker="Levels"
      description="Reward server activity with XP and level-up announcements."
      active={isModuleActive(props.settings, "levels")}
    >
      <Toggle
        label="Give XP for messages"
        checked={levels.enabled}
        onChange={props.onEnabledChange}
      />
      <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
            Level-up announcement
          </span>
          <select
            value={levels.announce}
            aria-invalid={props.fieldErrors["levels.announce"] ? true : undefined}
            onChange={(event) => props.onAnnounceChange(event.target.value as AnnounceMode)}
            className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
              props.fieldErrors["levels.announce"] ? "border-primary" : "border-line"
            }`}
          >
            <option value="dm">Direct message</option>
            <option value="channel">In a channel</option>
            <option value="off">Don't announce</option>
          </select>
          {props.fieldErrors["levels.announce"] && (
            <p className="text-primary mt-1 text-xs">{props.fieldErrors["levels.announce"]}</p>
          )}
        </label>
        {levels.announce === "channel" && (
          <ChannelSelect
            label="Announcement channel"
            value={levels.announce_channel}
            channels={props.channels}
            error={props.fieldErrors["levels.announce_channel"]}
            onChange={props.onAnnounceChannelChange}
          />
        )}
      </div>
      <div className="mt-5 grid gap-5 sm:grid-cols-3">
        <NumberField
          label="XP minimum"
          value={levels.xp_min}
          min={1}
          max={100}
          error={props.fieldErrors["levels.xp_min"]}
          onChange={props.onXpMinChange}
        />
        <NumberField
          label="XP maximum"
          value={levels.xp_max}
          min={1}
          max={100}
          error={props.fieldErrors["levels.xp_max"]}
          onChange={props.onXpMaxChange}
        />
        <NumberField
          label="Cooldown"
          suffix="seconds"
          value={levels.cooldown}
          min={0}
          max={3600}
          error={props.fieldErrors["levels.cooldown"]}
          onChange={props.onCooldownChange}
        />
      </div>
      <div className="mt-6 grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <IgnoreListEditor
          label="Channels without XP"
          prefix="#"
          value={levels.ignored_channels}
          options={props.channels}
          error={props.fieldErrors["levels.ignored_channels"]}
          onChange={props.onIgnoredChannelsChange}
        />
        <IgnoreListEditor
          label="Roles without XP"
          prefix="@"
          value={levels.ignored_roles}
          options={props.roles}
          error={props.fieldErrors["levels.ignored_roles"]}
          onChange={props.onIgnoredRolesChange}
        />
      </div>
    </Section>
  );
}

interface ChannelSectionProps {
  settings: GuildSettings;
  channels: GuildChannel[];
  fieldErrors: FieldErrors;
  onChange: ChannelChange;
}

export function VoiceSection(props: ChannelSectionProps) {
  return (
    <Section
      id="voice"
      icon="users-three"
      kicker="Voice reports"
      description="Choose where completed voice-session reports are published."
      active={isModuleActive(props.settings, "voice")}
    >
      <div className="max-w-md border-t border-line pt-6">
        <ChannelSelect
          label="Voice report channel"
          value={props.settings.voice_report_channel}
          channels={props.channels}
          error={props.fieldErrors.voice_report_channel}
          onChange={props.onChange}
        />
      </div>
    </Section>
  );
}

interface UpdatesSectionProps {
  settings: GuildSettings;
  channels: GuildChannel[];
  fieldErrors: FieldErrors;
  onUpdateChannelChange: ChannelChange;
  onGithubChannelChange: ChannelChange;
}

export function UpdatesSection(props: UpdatesSectionProps) {
  return (
    <Section
      id="updates"
      icon="arrows-clockwise"
      kicker="Updates"
      description="Route NovaGuard releases and repository activity into this server."
      active={isModuleActive(props.settings, "updates")}
    >
      <div className="grid gap-5 border-t border-line pt-6 sm:grid-cols-2">
        <ChannelSelect
          label="NovaGuard update channel"
          value={props.settings.update_channel}
          channels={props.channels}
          error={props.fieldErrors.update_channel}
          onChange={props.onUpdateChannelChange}
        />
        <ChannelSelect
          label="GitHub event channel"
          value={props.settings.github_event_channel}
          channels={props.channels}
          error={props.fieldErrors.github_event_channel}
          onChange={props.onGithubChannelChange}
        />
      </div>
    </Section>
  );
}
