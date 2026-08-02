// Build-time refresh of the baked release archive.
//
// The /updates page bakes src/data/updates-archive.json into static pages and
// only shows *newer* live entries via client JS on page one. Without this step
// the baked archive ages: releases published since the last site deploy exist
// only in the live tail, never in the static pages, the pagination, or for
// visitors without JS. Running this before `astro build` re-bakes the newest
// feed from the bot API.
//
// Fails soft on purpose: no network, a down bot, or a malformed/shrunken feed
// all keep the archive that is already committed — a stale page beats a broken
// or shrinking one. (The engine's state has been reset before; a shorter feed
// signals upstream data loss, never a reason to shrink the published record.)
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const FEED_URL =
  process.env.UPDATES_FEED_URL || "https://api.novaguard.fun/api/v1/updates?limit=200";
const FETCH_TIMEOUT_MS = 10_000;

export function isValidEntry(entry) {
  return (
    !!entry &&
    typeof entry === "object" &&
    typeof entry.created_at === "string" &&
    !Number.isNaN(Date.parse(entry.created_at)) &&
    Number.isInteger(entry.build)
  );
}

export function shouldReplaceArchive(current, fetched) {
  if (!Array.isArray(fetched) || fetched.length === 0) return false;
  if (!fetched.every(isValidEntry)) return false;
  const currentLength = Array.isArray(current) ? current.length : 0;
  return fetched.length >= currentLength;
}

async function main() {
  // Resolved here, not at module top level: the test runner imports this file
  // for its pure helpers under a non-file: URL where fileURLToPath throws.
  const archivePath = fileURLToPath(new URL("../src/data/updates-archive.json", import.meta.url));
  let current = [];
  try {
    current = JSON.parse(await readFile(archivePath, "utf8"));
  } catch {
    // Missing or unreadable baked archive — any valid feed is an upgrade.
  }

  let fetched;
  try {
    const response = await fetch(FEED_URL, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!response.ok) throw new Error(`feed answered ${response.status}`);
    fetched = (await response.json())?.updates;
  } catch (error) {
    console.log(
      `sync-updates-archive: keeping baked archive (${current.length} entries) — ` +
        `${error instanceof Error ? error.message : "feed unreachable"}`,
    );
    return;
  }

  if (!shouldReplaceArchive(current, fetched)) {
    console.log(
      `sync-updates-archive: keeping baked archive (${current.length} entries) — ` +
        `feed had ${Array.isArray(fetched) ? fetched.length : 0} usable entries`,
    );
    return;
  }

  await writeFile(archivePath, `${JSON.stringify(fetched, null, 2)}\n`);
  console.log(
    `sync-updates-archive: baked archive refreshed ${current.length} -> ${fetched.length} entries`,
  );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
