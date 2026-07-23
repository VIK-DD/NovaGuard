import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  useParams,
} from "@tanstack/react-router";
import AuthGate from "./components/AuthGate";
import Shell from "./components/Shell";
import GuildPicker from "./screens/GuildPicker";
import GuildConfig from "./screens/GuildConfig";
import AuditLog from "./screens/AuditLog";

function GuildLayout() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const tab = "border-b-2 px-1 pb-2 text-sm transition-colors";
  return (
    <>
      <nav className="border-b border-line">
        <div className="mx-auto flex max-w-3xl gap-6 px-6 pt-4">
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
        <Outlet />
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
