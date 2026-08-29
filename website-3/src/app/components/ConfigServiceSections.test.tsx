import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiSection, EconomySection } from "./ConfigServiceSections";
import {
  aiStatus,
  channels,
  createSettings,
  economyStatus,
} from "./ConfigSections.testData";

afterEach(cleanup);

describe("AiSection", () => {
  it("shows provider capacity and routes AI setting edits", () => {
    const onEnabled = vi.fn();
    const onAnswerMode = vi.fn();
    render(
      <AiSection
        settings={createSettings()}
        status={aiStatus}
        channels={channels}
        fieldErrors={{}}
        onEnabledChange={onEnabled}
        onChannelChange={() => undefined}
        onAnswerModeChange={onAnswerMode}
        onQuestionLimitChange={() => undefined}
      />,
    );

    expect(screen.getByText("Claude is available")).toBeInTheDocument();
    expect(screen.getByText(/1\/10 requests/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Enable /ask on this server" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Answer visibility" }), {
      target: { value: "public" },
    });
    expect(onEnabled).toHaveBeenCalledWith(true);
    expect(onAnswerMode).toHaveBeenCalledWith("public");
  });

  it("does not expose provider-ready text when the host integration is absent", () => {
    render(
      <AiSection
        settings={createSettings()}
        status={{ ...aiStatus, available: false, model: null }}
        channels={channels}
        fieldErrors={{}}
        onEnabledChange={() => undefined}
        onChannelChange={() => undefined}
        onAnswerModeChange={() => undefined}
        onQuestionLimitChange={() => undefined}
      />,
    );
    expect(screen.getByText("Host setup needed")).toBeInTheDocument();
    expect(screen.queryByText("Provider ready")).not.toBeInTheDocument();
  });
});

describe("EconomySection", () => {
  it("renders live status and emits narrow settings patches", () => {
    const onChange = vi.fn();
    render(
      <EconomySection
        settings={createSettings()}
        status={economyStatus}
        fieldErrors={{}}
        onChange={onChange}
      />,
    );

    expect(screen.getByText("3,456")).toBeInTheDocument();
    expect(screen.getByText("Nova Tester")).toBeInTheDocument();
    expect(screen.getByText(/Mystery crate/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: "Enable gamble and slots" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Base daily reward (coins)" }), {
      target: { value: "250" },
    });
    expect(onChange).toHaveBeenCalledWith({ games_enabled: false });
    expect(onChange).toHaveBeenCalledWith({ daily_base: 250 });
  });
});
