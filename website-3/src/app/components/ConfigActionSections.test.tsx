import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GiveawaySection } from "./ConfigGiveawaySection";
import { RolePanelsSection } from "./ConfigRolePanelsSection";
import {
  channels,
  createSettings,
  giveaways,
  rolePanels,
  roles,
  tickets,
} from "./ConfigSections.testData";
import { TicketSection } from "./ConfigTicketSection";

afterEach(cleanup);

describe("TicketSection", () => {
  it("keeps publishing and Discord navigation wired", () => {
    const draft = createSettings();
    draft.ticket_panel_channel = "1";
    draft.ticket_staff_role = "11";
    const onPublish = vi.fn();
    render(
      <TicketSection
        guildId="999"
        settings={draft}
        tickets={tickets}
        channels={channels}
        roles={roles}
        fieldErrors={{}}
        dirty={false}
        publishPending={false}
        publishError={false}
        notice={null}
        onChannelChange={() => undefined}
        onRoleChange={() => undefined}
        onPublish={onPublish}
      />,
    );

    expect(screen.queryByRole("option", { name: "Member" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Update panel" }));
    expect(onPublish).toHaveBeenCalledOnce();
    expect(screen.getByRole("link", { name: "Open in Discord ↗" })).toHaveAttribute(
      "href",
      "https://discord.com/channels/999/101",
    );
  });

  it("does not publish while settings are unsaved", () => {
    const draft = createSettings();
    draft.ticket_panel_channel = "1";
    draft.ticket_staff_role = "11";
    render(
      <TicketSection
        guildId="999"
        settings={draft}
        tickets={tickets}
        channels={channels}
        roles={roles}
        fieldErrors={{}}
        dirty={true}
        publishPending={false}
        publishError={false}
        notice={null}
        onChannelChange={() => undefined}
        onRoleChange={() => undefined}
        onPublish={() => undefined}
      />,
    );
    expect(screen.getByRole("button", { name: "Update panel" })).toBeDisabled();
  });
});

describe("RolePanelsSection", () => {
  it("routes editor fields, publish and tracked-panel selection", () => {
    const draft = createSettings();
    draft.role_panel_channel = "1";
    const onTitleChange = vi.fn();
    const onEdit = vi.fn();
    const onPublish = vi.fn();
    render(
      <RolePanelsSection
        guildId="999"
        settings={draft}
        panels={rolePanels}
        channels={channels}
        roles={roles}
        fieldErrors={{}}
        dirty={false}
        title="New panel"
        description="Choose a role"
        roleIds={["10"]}
        editingId={null}
        notice={null}
        publishPending={false}
        publishError={false}
        onChannelChange={() => undefined}
        onTitleChange={onTitleChange}
        onDescriptionChange={() => undefined}
        onRoleIdsChange={() => undefined}
        onCancelEdit={() => undefined}
        onEdit={onEdit}
        onPublish={onPublish}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Panel title" }), {
      target: { value: "Updated panel" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Publish panel" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onTitleChange).toHaveBeenCalledWith("Updated panel");
    expect(onPublish).toHaveBeenCalledOnce();
    expect(onEdit).toHaveBeenCalledWith(rolePanels[0]);
  });
});

describe("GiveawaySection", () => {
  it("keeps start, confirmed end and reroll actions distinct", () => {
    const draft = createSettings();
    draft.giveaway_channel = "1";
    const onStart = vi.fn();
    const onEnd = vi.fn();
    const onReroll = vi.fn();
    render(
      <GiveawaySection
        guildId="999"
        settings={draft}
        giveaways={giveaways}
        channels={channels}
        fieldErrors={{}}
        dirty={false}
        prize="Another prize"
        duration="1d"
        winners={1}
        notice={null}
        confirmEndId="300"
        startPending={false}
        startError={false}
        managePending={false}
        manageError={false}
        managingMessageId={null}
        onChannelChange={() => undefined}
        onPrizeChange={() => undefined}
        onDurationChange={() => undefined}
        onWinnersChange={() => undefined}
        onStart={onStart}
        onConfirmEndChange={() => undefined}
        onEnd={onEnd}
        onReroll={onReroll}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Start giveaway" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm end" }));
    fireEvent.click(screen.getByRole("button", { name: "Reroll" }));
    expect(onStart).toHaveBeenCalledOnce();
    expect(onEnd).toHaveBeenCalledWith("300");
    expect(onReroll).toHaveBeenCalledWith("301");
    expect(screen.getAllByRole("link", { name: "Open ↗" })[0]).toHaveAttribute(
      "href",
      "https://discord.com/channels/999/1/300",
    );
  });
});
