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
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3 sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center gap-4 sm:gap-6">
            <a href="/" className="flex items-center gap-2.5" aria-label="NovaGuard home">
              <img src="/favicon.png" alt="" width="28" height="28" className="h-7 w-7" />
              <span className="font-display whitespace-nowrap text-lg font-semibold tracking-tight">NovaGuard</span>
            </a>
            <Link
              to="/"
              className="hidden shrink-0 text-sm text-ink-muted transition-colors hover:text-ink sm:block"
            >
              Servers
            </Link>
          </div>
          {user && (
            <div className="flex min-w-0 items-center gap-2 text-sm sm:gap-3">
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
              <span className="max-w-[7rem] truncate sm:max-w-none">{user.username}</span>
              <button
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
                className="shrink-0 text-ink-muted transition-colors hover:text-ink disabled:opacity-50"
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
