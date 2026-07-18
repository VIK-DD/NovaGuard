import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";
import AuthGate from "./components/AuthGate";
import Shell from "./components/Shell";
import GuildPicker from "./screens/GuildPicker";
import GuildConfig from "./screens/GuildConfig";

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
  component: () => <Outlet />,
});

const guildConfigRoute = createRoute({
  getParentRoute: () => guildRoute,
  path: "/",
  component: GuildConfig,
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
