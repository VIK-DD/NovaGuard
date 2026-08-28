import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GuildChannel, GuildRole, GuildSettings } from "../../lib/api/schemas";
import {
  LevelsSection,
  ModerationSection,
  UpdatesSection,
  VoiceSection,
  WelcomeSection,
} from "./ConfigCoreSections";

afterEach(cleanup);

const channels: GuildChannel[] = [
  { id: "1", name: "general", category: null },
  { id: "2", name: "staff", category: "Team" },
];
const roles: GuildRole[] = [
  { id: "10", name: "Member", color: "#5865f2", assignable: true, manages_threads: false },
  { id: "11", name: "Owner", color: "#ed4245", assignable: false, manages_threads: true },
];

const settings = (): GuildSettings => ({
  welcome_channel: "1",
  goodbye_channel: null,
  log_channel: "2",
  voice_report_channel: null,
  update_channel: null,
  github_event_channel: null,
  error_log_channel: null,
  ticket_panel_channel: null,
  role_panel_channel: null,
  giveaway_channel: null,
  autorole: "10",
  ticket_staff_role: null,
  automod: {
    invites: true,
    spam: false,
    badwords: [],
    ignored_channels: [],
    ignored_roles: [],
    spam_messages: 6,
    spam_window_seconds: 6,
    spam_timeout_seconds: 60,
  },
  levels: {
    enabled: true,
    announce: "dm",
    announce_channel: null,
    xp_min: 5,
    xp_max: 10,
    cooldown: 120,
    ignored_channels: [],
    ignored_roles: [],
  },
  ai: {
    enabled: false,
    answer_mode: "private",
    channel_id: null,
    max_question_chars: 2000,
  },
  economy: {
    enabled: true,
    daily_base: 200,
    daily_streak_bonus: 50,
    work_min: 50,
    work_max: 150,
    work_cooldown_minutes: 60,
    transfers_enabled: true,
    games_enabled: true,
    shop_enabled: true,
    gamble_max_bet: 1000,
    slots_max_bet: 500,
  },
});

describe("WelcomeSection", () => {
  it("routes channel and role edits through the supplied handlers", () => {
    const onWelcome = vi.fn();
    const onAutorole = vi.fn();
    render(
      <WelcomeSection
        settings={settings()}
        channels={channels}
        roles={roles}
        fieldErrors={{}}
        onWelcomeChannelChange={onWelcome}
        onGoodbyeChannelChange={() => undefined}
        onAutoroleChange={onAutorole}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Welcome channel" }), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Auto-role for newcomers" }), {
      target: { value: "" },
    });
    expect(onWelcome).toHaveBeenCalledWith("2");
    expect(onAutorole).toHaveBeenCalledWith(null);
    expect(screen.queryByRole("option", { name: "Owner" })).not.toBeInTheDocument();
  });
});

describe("ModerationSection", () => {
  it("preserves switch and threshold behavior after extraction", () => {
    const onInvites = vi.fn();
    const onMessages = vi.fn();
    render(
      <ModerationSection
        settings={settings()}
        channels={channels}
        roles={roles}
        fieldErrors={{}}
        onLogChannelChange={() => undefined}
        onErrorLogChannelChange={() => undefined}
        onInvitesChange={onInvites}
        onSpamChange={() => undefined}
        onBadwordsChange={() => undefined}
        onIgnoredChannelsChange={() => undefined}
        onIgnoredRolesChange={() => undefined}
        onSpamMessagesChange={onMessages}
        onSpamWindowChange={() => undefined}
        onSpamTimeoutChange={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole("switch", { name: "Block Discord invites" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Messages (to trigger)" }), {
      target: { value: "8" },
    });
    expect(onInvites).toHaveBeenCalledWith(false);
    expect(onMessages).toHaveBeenCalledWith(8);
  });
});

describe("LevelsSection", () => {
  it("shows the announcement channel only for channel mode", () => {
    const draft = settings();
    draft.levels.announce = "channel";
    draft.levels.announce_channel = "1";
    const onAnnounce = vi.fn();
    render(
      <LevelsSection
        settings={draft}
        channels={channels}
        roles={roles}
        fieldErrors={{}}
        onEnabledChange={() => undefined}
        onAnnounceChange={onAnnounce}
        onAnnounceChannelChange={() => undefined}
        onXpMinChange={() => undefined}
        onXpMaxChange={() => undefined}
        onCooldownChange={() => undefined}
        onIgnoredChannelsChange={() => undefined}
        onIgnoredRolesChange={() => undefined}
      />,
    );

    expect(screen.getByRole("combobox", { name: "Announcement channel" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Level-up announcement" }), {
      target: { value: "off" },
    });
    expect(onAnnounce).toHaveBeenCalledWith("off");
  });
});

describe("channel-only sections", () => {
  it("retain the voice and update channel controls", () => {
    const draft = settings();
    const { rerender } = render(
      <VoiceSection
        settings={draft}
        channels={channels}
        fieldErrors={{}}
        onChange={() => undefined}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Voice report channel" })).toBeInTheDocument();

    rerender(
      <UpdatesSection
        settings={draft}
        channels={channels}
        fieldErrors={{}}
        onUpdateChannelChange={() => undefined}
        onGithubChannelChange={() => undefined}
      />,
    );
    expect(screen.getByRole("combobox", { name: "NovaGuard update channel" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "GitHub event channel" })).toBeInTheDocument();
  });
});
