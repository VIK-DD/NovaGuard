const DASHBOARD_FALLBACK = "/dashboard/";

/**
 * Keeps public CTAs useful before any browser script has loaded. The dashboard
 * can enhance itself after load, but an invitation must be correct in the
 * static HTML too—for visitors who block JavaScript or open it slowly.
 */
export function publicInviteUrl(apiBase = import.meta.env.PUBLIC_API_BASE): string {
  if (!apiBase) return DASHBOARD_FALLBACK;

  try {
    const url = new URL(apiBase);
    if (url.protocol !== "https:" && url.protocol !== "http:") return DASHBOARD_FALLBACK;
    return `${url.origin}/api/v1/invite`;
  } catch {
    return DASHBOARD_FALLBACK;
  }
}
