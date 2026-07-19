// Soft-launch: after `astro build`, physically overwrite dist/index.html
// (and its assets) with the legacy Coming Soon page. This avoids relying on
// _redirects rewrite (200) rules, which some static hosts (e.g. Cloudflare
// Workers static assets, unlike classic Pages) don't honor — only real
// redirects (3xx) are guaranteed to work everywhere.
//
// Public launch: delete the `node scripts/soft-launch.mjs` step from the
// "build" script in package.json and redeploy. See README.md.
import { cp, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const comingSoon = fileURLToPath(new URL("../dist/coming-soon/", import.meta.url));

if (!existsSync(comingSoon)) {
  console.error("soft-launch: dist/coming-soon not found — run `astro build` first");
  process.exit(1);
}

const entries = await readdir(comingSoon, { withFileTypes: true });
for (const entry of entries) {
  await cp(`${comingSoon}${entry.name}`, `${dist}${entry.name}`, { recursive: true });
}

console.log(
  `soft-launch: copied ${entries.map((e) => e.name).join(", ")} from coming-soon/ onto dist root`,
);
