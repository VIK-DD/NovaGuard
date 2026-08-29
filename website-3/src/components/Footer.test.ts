import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The footer is on every page, so a link that rots here rots site-wide, and
// it rots quietly: nobody clicks their own footer. Checking the hrefs against
// the pages that actually exist is cheap insurance against renaming a route
// and leaving nine pages pointing at a 404.

const footer = readFileSync(
  resolve(process.cwd(), "src/components/Footer.astro"),
  "utf8",
);

function internalLinks(): string[] {
  return [...footer.matchAll(/href="(\/[^"]*)"/g)].map((match) => match[1]);
}

function pageExists(href: string): boolean {
  const route = href.replace(/^\//, "").replace(/\/$/, "");
  const pages = resolve(process.cwd(), "src/pages");
  return (
    existsSync(resolve(pages, `${route}.astro`)) ||
    existsSync(resolve(pages, route, "index.astro")) ||
    // A route directory holding a rest-route file, e.g. updates/[...page].astro
    (existsSync(resolve(pages, route)) &&
      readdirSync(resolve(pages, route)).some((name) => name.endsWith(".astro")))
  );
}

describe("Footer", () => {
  it("links only to pages that exist", () => {
    const missing = internalLinks().filter((href) => !pageExists(href));

    expect(missing).toEqual([]);
  });

  it("offers both a product and a legal column", () => {
    expect(footer).toContain('aria-label="Product"');
    expect(footer).toContain('aria-label="Legal"');
  });

  it("balances navigation with a real brand and community panel", () => {
    expect(footer).toContain('/assets/novaguard-icon-96.png');
    expect(footer).toContain('aria-label="Community"');
    expect(footer).toContain('href="https://discord.gg/CbDy3GyhWm"');
    expect(footer).toContain('href="/vote"');
    expect(footer).toContain("Vote on Top.gg");
    expect(footer).toContain("Powerful Discord moderation and utilities");
    expect(footer).not.toContain("Open Beta");
    expect(footer).toContain("Developed by VIK &amp; CloudMedia");
    expect(footer.toLowerCase()).not.toContain("names");
    expect(footer).toContain('viewBox="-6 -6 139.14 108.36"');
  });

  it("does not advertise social accounts that do not exist yet", () => {
    expect(footer).not.toContain("instagram.com");
    expect(footer).not.toContain("twitter.com");
    expect(footer).not.toContain("x.com/");
  });

  it("keeps every navigation link inside a labelled nav", () => {
    // Screen readers announce the group; loose links in the footer arrive as
    // an unexplained pile.
    const navSections = footer.match(/<nav[\s\S]*?<\/nav>/g) ?? [];
    const linksInNavs = navSections.flatMap(
      (section) => [...section.matchAll(/href="(\/[^"]*)"/g)].map((m) => m[1]),
    );

    expect(new Set(linksInNavs)).toEqual(new Set(internalLinks()));
  });
});
