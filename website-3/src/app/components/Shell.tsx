import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useLogout, useMe } from "../queries";

export default function Shell({ children }: { children: ReactNode }) {
  const me = useMe();
  const logout = useLogout();
  const user = me.data?.user;

  return (
    <div className="min-h-screen">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-6">
            <a href="/" className="flex items-center gap-2.5" aria-label="NovaGuard home">
              <img src="/favicon.png" alt="" width="28" height="28" className="h-7 w-7" />
              <span className="font-display text-lg font-semibold tracking-tight">NovaGuard</span>
            </a>
            <Link
              to="/"
              className="text-sm text-ink-muted transition-colors hover:text-ink"
            >
              Servers
            </Link>
          </div>
          {user && (
            <div className="flex items-center gap-3 text-sm">
              {user.avatar ? (
                <img
                  src={`https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=64`}
                  alt=""
                  className="h-7 w-7 rounded-full border border-line"
                />
              ) : (
                <span className="font-display flex h-7 w-7 items-center justify-center rounded-full border border-line">
                  {user.username.charAt(0).toUpperCase()}
                </span>
              )}
              <span>{user.username}</span>
              <button
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
                className="text-ink-muted transition-colors hover:text-ink disabled:opacity-50"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>
      {children}
    </div>
  );
}
