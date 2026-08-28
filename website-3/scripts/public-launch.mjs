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
