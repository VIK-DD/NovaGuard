import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LevelsSection,
  ModerationSection,
  UpdatesSection,
  VoiceSection,
  WelcomeSection,
} from "./ConfigCoreSections";
import { channels, createSettings, roles } from "./ConfigSections.testData";

afterEach(cleanup);

describe("WelcomeSection", () => {
  it("routes channel and role edits through the supplied handlers", () => {
    const onWelcome = vi.fn();
    const onAutorole = vi.fn();
    render(
      <WelcomeSection
        settings={createSettings()}
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
        settings={createSettings()}
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
    const draft = createSettings();
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
    const draft = createSettings();
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
