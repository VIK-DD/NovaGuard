import { describe, expect, it } from "vitest";
import { getPrivacySafetySignals, type PrivacySafetySettings } from "./privacySafety";

function settings(overrides: Partial<PrivacySafetySettings> = {}): PrivacySafetySettings {
  return {
    log_channel: null,
    voice_report_channel: null,
    ticket_panel_channel: null,
    ticket_staff_role: null,
    automod: { invites: false, spam: false, badwords: [] },
    levels: { enabled: false },
    ai: { enabled: false },
    economy: { enabled: false },
    ...overrides,
  };
}

describe("getPrivacySafetySignals", () => {
  it("keeps every high-impact item off when its feature is off", () => {
    const signals = getPrivacySafetySignals(settings());

    expect(signals).toHaveLength(6);
    expect(signals.filter((signal) => signal.active)).toEqual([]);
  });

  it("reports the precise active member-facing effects", () => {
    const signals = getPrivacySafetySignals(
      settings({
        log_channel: "100",
        levels: { enabled: true },
        ai: { enabled: true },
        economy: { enabled: true },
      }),
    );

    expect(signals.filter((signal) => signal.active).map((signal) => signal.moduleId)).toEqual([
      "moderation",
      "levels",
      "ai",
      "economy",
    ]);
    expect(signals.find((signal) => signal.moduleId === "moderation")?.activeLabel).toBe(
      "Logs active",
    );
  });

  it("still flags AutoMod when no log channel is configured", () => {
    const [moderation] = getPrivacySafetySignals(
      settings({ automod: { invites: true, spam: false, badwords: [] } }),
    );

    expect(moderation.active).toBe(true);
    expect(moderation.activeLabel).toBe("AutoMod active");
  });
});
