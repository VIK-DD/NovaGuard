/**
 * Astro's development server does not read Cloudflare's `_redirects` file.
 * Keep dashboard deep links on their original browser URL while serving the
 * React router shell, matching the production Worker's behaviour.
 */
export function dashboardShellUrl(rawUrl) {
  if (typeof rawUrl !== "string") return rawUrl;

  const queryIndex = rawUrl.indexOf("?");
  const pathname = queryIndex === -1 ? rawUrl : rawUrl.slice(0, queryIndex);
  if (pathname === "/dashboard/" || !pathname.startsWith("/dashboard/")) return rawUrl;

  return queryIndex === -1 ? "/dashboard/" : `/dashboard/${rawUrl.slice(queryIndex)}`;
}

export function dashboardSpaFallback() {
  return {
    name: "novaguard-dashboard-spa-fallback",
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        request.url = dashboardShellUrl(request.url);
        next();
      });
    },
  };
}
