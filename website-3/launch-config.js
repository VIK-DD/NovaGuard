export const PUBLIC_LAUNCH_AT = "2026-09-01T00:00:00+03:00";
export const PUBLIC_LAUNCH_PATH = "/home/";

export const PUBLIC_LAUNCH_AT_MS = Date.parse(PUBLIC_LAUNCH_AT);

if (!Number.isFinite(PUBLIC_LAUNCH_AT_MS)) {
  throw new Error(`Invalid PUBLIC_LAUNCH_AT value: ${PUBLIC_LAUNCH_AT}`);
}

export function hasPublicLaunchPassed(now = Date.now()) {
  const timestamp = now instanceof Date ? now.getTime() : Number(now);
  return Number.isFinite(timestamp) && timestamp >= PUBLIC_LAUNCH_AT_MS;
}
