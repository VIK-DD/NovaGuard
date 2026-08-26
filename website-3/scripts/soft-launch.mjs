// Soft-launch: after `astro build`, physically overwrite dist/index.html
// (and its assets) with the legacy Coming Soon page. This avoids relying on
// _redirects rewrite (200) rules, which some static hosts (e.g. Cloudflare
// Workers static assets, unlike classic Pages) don't honor — only real
// redirects (3xx) are guaranteed to work everywhere.
//
// Public launch: delete the `node scripts/soft-launch.mjs` step from the
// "build" script in package.json and redeploy. See README.md.
import { cp, readFile, readdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const comingSoon = fileURLToPath(new URL("../dist/coming-soon/", import.meta.url));
const manropeSource = fileURLToPath(
  new URL("../node_modules/@fontsource-variable/manrope/files/manrope-latin-wght-normal.woff2", import.meta.url),
);
const dmMonoSource = fileURLToPath(
  new URL("../node_modules/@fontsource/dm-mono/files/dm-mono-latin-400-normal.woff2", import.meta.url),
);
const manropeLicense = fileURLToPath(
  new URL("../node_modules/@fontsource-variable/manrope/LICENSE", import.meta.url),
);
const dmMonoLicense = fileURLToPath(
  new URL("../node_modules/@fontsource/dm-mono/LICENSE", import.meta.url),
);

if (!existsSync(comingSoon)) {
  console.error("soft-launch: dist/coming-soon not found - run `astro build` first");
  process.exit(1);
}

// The preserved page was originally built with a Google Fonts @import. The
// production CSP correctly refuses it, so make the deployed artifact genuinely
// self-contained instead of silently falling back to system fonts.
const comingSoonAssets = `${comingSoon}assets/`;
await cp(manropeSource, `${comingSoonAssets}manrope-latin-wght-normal.woff2`);
await cp(dmMonoSource, `${comingSoonAssets}dm-mono-latin-400-normal.woff2`);
const [manropeLicenseText, dmMonoLicenseText] = await Promise.all([
  readFile(manropeLicense, "utf8"),
  readFile(dmMonoLicense, "utf8"),
]);
await writeFile(
  `${comingSoonAssets}THIRD-PARTY-FONT-LICENSES.txt`,
  [
    "Manrope\n=======\n",
    manropeLicenseText.trim(),
    "\n\nDM Mono\n=======\n",
    dmMonoLicenseText.trim(),
    "\n",
  ].join(""),
  "utf8",
);
const fontFaces =
  '@font-face{font-family:Manrope;font-style:normal;font-display:swap;font-weight:200 800;src:url("./manrope-latin-wght-normal.woff2") format("woff2")}' +
  '@font-face{font-family:"DM Mono";font-style:normal;font-display:swap;font-weight:400;src:url("./dm-mono-latin-400-normal.woff2") format("woff2")}';
for (const asset of await readdir(comingSoonAssets)) {
  if (!asset.endsWith(".css")) continue;
  const path = `${comingSoonAssets}${asset}`;
  const css = await readFile(path, "utf8");
  const localCss = css.replace(
    /^@import["']https:\/\/fonts\.googleapis\.com\/[^;]+;/,
    fontFaces,
  );
  if (localCss.includes("fonts.googleapis.com")) {
    throw new Error(`soft-launch: remote Google Fonts import remains in ${asset}`);
  }
  await writeFile(path, localCss, "utf8");
}

const entries = await readdir(comingSoon, { withFileTypes: true });
for (const entry of entries) {
  await cp(`${comingSoon}${entry.name}`, `${dist}${entry.name}`, { recursive: true });
}

console.log(
  `soft-launch: copied ${entries.map((e) => e.name).join(", ")} from coming-soon/ onto dist root`,
);
