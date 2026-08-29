import {
  PUBLIC_LAUNCH_AT,
  PUBLIC_LAUNCH_PATH,
} from "../launch-config.js";

const COUNTDOWN_REDIRECT_MARKER = "data-novaguard-public-launch";

export function countdownRedirectMarkup() {
  return `<script ${COUNTDOWN_REDIRECT_MARKER}>` +
    `(()=>{const launchAt=Date.parse(${JSON.stringify(PUBLIC_LAUNCH_AT)});` +
    `const destination=${JSON.stringify(PUBLIC_LAUNCH_PATH)};` +
    "const leave=()=>{if(Date.now()>=launchAt)window.location.replace(destination)};" +
    "leave();setInterval(leave,1000)})();" +
    "</script>";
}

export function injectCountdownRedirect(html) {
  if (html.includes(COUNTDOWN_REDIRECT_MARKER)) return html;
  if (!html.includes("</head>")) {
    throw new Error("public-launch: countdown HTML does not contain </head>");
  }
  return html.replace("</head>", `${countdownRedirectMarkup()}</head>`);
}

export function countdownBundleUsesLaunchDate(source) {
  return source.includes(PUBLIC_LAUNCH_AT);
}

// The URL is bounded by its own quote, never by a semicolon: Google Fonts
// separates weights with semicolons ("wght@400;500"), so a pattern that stops
// at the first one cuts the URL in half. That left the closing quote behind as
// an unmatched one, which opens a CSS string that runs to the end of the file
// and takes every rule after it with it — the page then loaded the fonts and
// nothing else. Backreference \1 makes the closing quote match the opening one.
const GOOGLE_FONTS_IMPORT = /@import\s*(["'])https:\/\/fonts\.googleapis\.com\/[^"']*\1\s*;/;

/**
 * Swap a remote Google Fonts @import for self-hosted @font-face rules.
 *
 * The production CSP refuses the remote stylesheet, so the deployed artifact
 * has to carry its own fonts. Everything after the import is kept exactly as
 * it was — this replaces one statement, not the sheet. Throwing rather than
 * returning the sheet unchanged is deliberate: a silent pass is how a page
 * shipped once with no styling at all.
 */
export function localizeFontImport(css, fontFaces) {
  const localized = css.replace(GOOGLE_FONTS_IMPORT, () => fontFaces);
  if (localized.includes("fonts.googleapis.com")) {
    throw new Error("public-launch: a remote fonts.googleapis.com import survived localization");
  }
  return localized;
}

/**
 * Append `?v=<token>` to the named assets wherever the document links them.
 *
 * This step rewrites an asset's contents but keeps its file name, and the edge
 * serves those names with `immutable` for a year. A browser holding the old
 * copy would never ask for the new one, so a corrected stylesheet would reach
 * new visitors only. The page HTML revalidates on every load, which is what
 * lets a token in the markup pull the corrected asset through.
 *
 * Already-stamped links are left alone, so running twice changes nothing.
 */
export function stampAssetVersions(html, versions) {
  let stamped = html;
  for (const [asset, token] of Object.entries(versions)) {
    const name = asset.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    stamped = stamped.replace(new RegExp(`(href="[^"]*${name})(")`, "g"), `$1?v=${token}$2`);
  }
  return stamped;
}
