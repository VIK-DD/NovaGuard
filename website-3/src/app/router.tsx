import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";
import AuthGate from "./components/AuthGate";
import Shell from "./components/Shell";

const rootRoute = createRootRoute({
  component: () => (
    <AuthGate>
      <Shell>
        <Outlet />
      </Shell>
    </AuthGate>
  ),
});

// Placeholder screens — replaced by real ones in later tasks.
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">Your servers</p>
    </main>
  ),
});

const guildRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/g/$guildId",
  component: () => <Outlet />,
});

const guildConfigRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/",
  component: () => null,
});

const guildAuditRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/audit",
  component: () => null,
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
