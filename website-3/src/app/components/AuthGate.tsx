import type { ReactNode } from "react";
import { ApiError, loginUrl } from "../../lib/api/client";
import { useMe } from "../queries";

function Screen(props: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center px-6 text-center">
      <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">{props.kicker}</p>
      <h1 className="font-display mt-4 text-4xl">{props.title}</h1>
      {props.children}
    </main>
  );
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();

  if (me.isPending) {
    return <Screen kicker="NovaGuard" title="Checking your session…" />;
  }

  if (me.isError) {
    const err = me.error;
    const code = err instanceof ApiError ? err.code : "internal_error";

    if (code === "unauthorized" || code === "session_expired") {
      return (
        <Screen kicker="NovaGuard dashboard" title="Sign in to take the helm.">
          <p className="mt-3 text-sm text-ink-muted">
            Use your Discord account. You will only see servers you can manage.
          </p>
          <button
            onClick={() => window.location.assign(loginUrl())}
            className="bg-accent-solid mt-8 rounded-full px-6 py-3 text-white transition-opacity hover:opacity-90"
          >
            Continue with Discord
          </button>
        </Screen>
      );
    }

    return (
      <Screen kicker="NovaGuard dashboard" title="The bot is unreachable.">
        <p className="mt-3 text-sm text-ink-muted">
          {code === "bot_starting"
            ? "NovaGuard is starting up — give it a moment."
            : "Check that the bot is online, then try again."}
        </p>
        <button
          onClick={() => void me.refetch()}
          className="mt-8 rounded-full border border-line px-6 py-3 transition-colors hover:border-ink"
        >
          Retry
        </button>
      </Screen>
    );
  }

  return <>{children}</>;
}
