import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  useParams,
} from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import AuthGate from "./components/AuthGate";
import Shell from "./components/Shell";

const GuildPicker = lazy(() => import("./screens/GuildPicker"));
const GuildOverview = lazy(() => import("./screens/GuildOverview"));
const GuildConfig = lazy(() => import("./screens/GuildConfig"));
const AuditLog = lazy(() => import("./screens/AuditLog"));

function RouteFallback() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16" aria-busy="true">
      <div className="h-8 w-1/3 animate-pulse rounded bg-line/60" />
    </main>
  );
}

function GuildLayout() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const queryClient = useQueryClient();
  const tab = "inline-flex min-h-11 items-center border-b-2 px-1 text-sm transition-colors";
  const warmAudit = () => {
    void import("./queries/audit").then(({ auditQuery }) =>
      queryClient.prefetchQuery(auditQuery(guildId)),
    );
  };
  return (
    <>
      <nav className="border-b border-line">
        <div className="mx-auto flex max-w-3xl gap-5 overflow-x-auto px-4 pt-4 pb-px [scrollbar-width:none] sm:gap-6 sm:px-6">
          <Link
            to="/"
            className={`${tab} shrink-0 border-transparent text-ink-muted hover:text-ink`}
          >
            ← Servers
          </Link>
          <Link
            to="/g/$guildId"
            params={{ guildId }}
            activeOptions={{ exact: true }}
            activeProps={{ className: `${tab} border-primary text-ink` }}
            inactiveProps={{ className: `${tab} border-transparent text-ink-muted hover:text-ink` }}
          >
            Overview
          </Link>
          <Link
            to="/g/$guildId/settings"
            params={{ guildId }}
            activeProps={{ className: `${tab} border-primary text-ink` }}
            inactiveProps={{ className: `${tab} border-transparent text-ink-muted hover:text-ink` }}
          >
            Modules
          </Link>
          <Link
            to="/g/$guildId/audit"
            params={{ guildId }}
            onMouseEnter={warmAudit}
            onFocus={warmAudit}
            activeProps={{ className: `${tab} border-primary text-ink` }}
            inactiveProps={{ className: `${tab} border-transparent text-ink-muted hover:text-ink` }}
          >
            Audit log
          </Link>
        </div>
      </nav>
      <Outlet />
    </>
  );
}

function DashboardNotFound() {
  return (
    <AuthGate>
      <Shell>
        <main className="mx-auto flex min-h-[65vh] max-w-3xl flex-col items-center justify-center px-6 text-center">
          <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">404</p>
          <h1 className="font-display mt-4 text-4xl">This dashboard page does not exist.</h1>
          <p className="mt-3 max-w-md text-sm text-ink-muted">
            The link may be outdated, or the page may have moved.
          </p>
          <Link
            to="/"
            className="ng-pressable mt-8 inline-flex min-h-11 items-center rounded-full border border-line px-5 text-sm transition-colors hover:border-line-strong"
          >
            Back to servers
          </Link>
        </main>
      </Shell>
    </AuthGate>
  );
}

const rootRoute = createRootRoute({
  component: () => (
      <AuthGate>
        <Shell>
          <Suspense fallback={<RouteFallback />}>
            <Outlet />
          </Suspense>
        </Shell>
      </AuthGate>
  ),
  notFoundComponent: DashboardNotFound,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: GuildPicker,
});

const guildRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/g/$guildId",
  component: GuildLayout,
});

const guildConfigRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/",
  component: GuildOverview,
});

const guildSettingsRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/settings",
  component: GuildConfig,
});

const guildAuditRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/audit",
  component: AuditLog,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  guildRoute.addChildren([guildConfigRoute, guildSettingsRoute, guildAuditRoute]),
]);

export const router = createRouter({ routeTree, basepath: "/dashboard" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
