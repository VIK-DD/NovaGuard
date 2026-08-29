import { describe, expect, it } from "vitest";
import { FAQ_ITEM_COUNT, FAQ_SECTIONS } from "./faq";

describe("FAQ_SECTIONS", () => {
  it("keeps a useful answer set across the four product topics", () => {
    expect(FAQ_SECTIONS.map((section) => section.id)).toEqual([
      "getting-started",
      "features-control",
      "privacy-data",
      "reliability-support",
    ]);
    expect(FAQ_ITEM_COUNT).toBeGreaterThanOrEqual(16);
  });

  it("has unique anchors and questions", () => {
    const ids = FAQ_SECTIONS.map((section) => section.id);
    const questions = FAQ_SECTIONS.flatMap((section) =>
      section.items.map((item) => item.question),
    );

    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(questions).size).toBe(questions.length);
  });

  it("keeps internal links absolute and external links secure", () => {
    const links = FAQ_SECTIONS.flatMap((section) =>
      section.items.flatMap((item) => item.links ?? []),
    );

    for (const link of links) {
      expect(link.label.trim().length).toBeGreaterThan(0);
      expect(link.href.startsWith("/") || link.href.startsWith("https://")).toBe(true);
    }
  });

  it("answers the free-use, permission and privacy questions explicitly", () => {
    const copy = JSON.stringify(FAQ_SECTIONS);

    expect(copy).toContain("free to use");
    expect(copy).toContain("never the blanket Administrator permission");
    expect(copy).toContain("does not sell personal data");
    expect(copy).toContain("/privacy export");
    expect(copy).toContain("30-day recovery window");
  });
});
