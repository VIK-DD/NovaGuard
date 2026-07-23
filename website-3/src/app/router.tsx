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
import { auditQuery } from "./queries";

const GuildPicker = lazy(() => import("./screens/GuildPicker"));
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
    void queryClient.prefetchQuery(auditQuery(guildId));
  };
  return (
    <>
      <nav className="border-b border-line">
        <div className="mx-auto flex max-w-3xl gap-5 overflow-x-auto px-4 pt-4 pb-px [scrollbar-width:none] sm:gap-6 sm:px-6">
          <Link
            to="/g/$guildId"
            params={{ guildId }}
            activeOptions={{ exact: true }}
            activeProps={{ className: `${tab} border-primary text-ink` }}
            inactiveProps={{ className: `${tab} border-transparent text-ink-muted hover:text-ink` }}
          >
            Configuration
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
  component: GuildConfig,
});

const guildAuditRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/audit",
  component: AuditLog,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  guildRoute.addChildren([guildConfigRoute, guildAuditRoute]),
]);

export const router = createRouter({ routeTree, basepath: "/dashboard" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
