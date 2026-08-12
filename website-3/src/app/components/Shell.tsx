import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useLogout, useMe } from "../queries";
import { useUnsavedChanges } from "../unsavedChanges";
import Icon from "./Icon";

export default function Shell({ children }: { children: ReactNode }) {
  const me = useMe();
  const logout = useLogout();
  const user = me.data?.user;
  const { hasUnsavedChanges, discardUnsavedChanges } = useUnsavedChanges();

  // Below sm, "Servers" had nowhere to go — it was simply hidden, with no
  // replacement. This drawer exists to carry exactly that back, not to
  // duplicate the tab nav GuildLayout already renders (that one scrolls fine
  // on its own and stays visible on every width).
  const [open, setOpen] = useState(false);
  const [confirmingSignOut, setConfirmingSignOut] = useState(false);
  const headerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointerDown = (e: PointerEvent) => {
      if (e.target instanceof Node && !headerRef.current?.contains(e.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown, { passive: true });
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  useEffect(() => {
    if (!confirmingSignOut) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmingSignOut(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [confirmingSignOut]);

  const requestSignOut = () => {
    if (hasUnsavedChanges) {
      setConfirmingSignOut(true);
      return;
    }
    logout.mutate();
  };

  const confirmSignOut = () => {
    discardUnsavedChanges();
    setConfirmingSignOut(false);
    logout.mutate();
  };

  return (
    <div className="min-h-screen">
      <header ref={headerRef} className="relative border-b border-line">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3 sm:px-6 sm:py-4">
          <div className="flex min-w-0 items-center">
            <a href="/home/" className="flex items-center gap-2.5" aria-label="NovaGuard home">
              <img
                src="/assets/novaguard-icon-96.png"
                alt=""
                width="28"
                height="28"
                className="h-7 w-7"
              />
              <span className="font-display whitespace-nowrap text-base font-semibold tracking-tight sm:text-lg">NovaGuard</span>
            </a>
          </div>
          <div className="flex min-w-0 items-center gap-1 sm:gap-3">
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
                <span className="hidden max-w-[7rem] truncate sm:inline sm:max-w-none">
                  {user.username}
                </span>
                <button
                  onClick={requestSignOut}
                  disabled={logout.isPending}
                  className="hidden min-h-11 shrink-0 px-2 text-ink-muted transition-colors hover:text-ink disabled:opacity-50 sm:inline-flex sm:min-h-0 sm:items-center sm:px-0"
                >
                  Sign out
                </button>
              </div>
            )}
            <button
              type="button"
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              aria-controls="shell-mobile-menu"
              onClick={() => setOpen((v) => !v)}
              className="ng-touch-target grid h-11 w-11 shrink-0 place-items-center rounded-[6px] border border-line text-ink transition-colors hover:border-line-strong sm:hidden"
            >
              <Icon name={open ? "x" : "list"} size={18} flat />
            </button>
          </div>
        </div>

        {/* Absolute so opening it never shifts the page underneath. */}
        <div
          id="shell-mobile-menu"
          aria-hidden={!open}
          inert={!open}
          className={`absolute inset-x-0 top-full z-30 origin-top border-b border-line bg-background shadow-[0_20px_30px_hsl(20_20%_2%/0.16)] transition-[translate,scale,opacity] duration-[240ms] ease-[cubic-bezier(0.16,1,0.3,1)] sm:hidden ${
            open
              ? "pointer-events-auto translate-y-0 scale-y-100 opacity-100"
              : "pointer-events-none -translate-y-1 scale-y-95 opacity-0"
          }`}
        >
          <nav className="flex flex-col gap-0.5 px-2 py-2">
            <Link
              to="/"
              onClick={() => setOpen(false)}
              className="flex min-h-11 items-center gap-2.5 rounded-[6px] px-3 text-sm text-ink-muted transition-colors hover:bg-card hover:text-ink"
            >
              <Icon name="house" size={18} />
              Servers
            </Link>
            {user && (
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  requestSignOut();
                }}
                disabled={logout.isPending}
                className="flex min-h-11 items-center gap-2.5 rounded-[6px] px-3 text-left text-sm text-ink-muted transition-colors hover:bg-card hover:text-ink disabled:opacity-50"
              >
                <Icon name="sign-out" size={18} />
                Sign out
              </button>
            )}
          </nav>
        </div>
      </header>
      {children}
      <footer className="mx-auto flex max-w-5xl flex-wrap gap-x-4 gap-y-2 border-t border-line px-4 py-6 text-xs text-ink-faint sm:px-6">
        <a href="/privacy" className="transition-colors hover:text-ink">
          Privacy &amp; cookies
        </a>
        <a href="/privacy#your-choices" className="transition-colors hover:text-ink">
          Export or erase data
        </a>
        <a href="/terms" className="transition-colors hover:text-ink">
          Terms
        </a>
      </footer>
      {confirmingSignOut && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 px-5 py-8"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setConfirmingSignOut(false);
          }}
        >
          <section
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="sign-out-title"
            aria-describedby="sign-out-description"
            className="w-full max-w-md rounded-[var(--radius-card)] border border-line bg-background p-6 shadow-[0_24px_80px_rgb(0_0_0/0.4)]"
          >
            <p className="text-xs tracking-[0.2em] text-primary uppercase">Unsaved changes</p>
            <h2 id="sign-out-title" className="font-display mt-2 text-2xl font-semibold">
              Sign out without saving?
            </h2>
            <p id="sign-out-description" className="mt-3 text-sm leading-6 text-ink-muted">
              Your recent settings changes will be discarded before you sign out.
            </p>
            <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={confirmSignOut}
                className="ng-touch-target inline-flex items-center justify-center rounded-full border border-line px-5 py-2 text-sm transition-colors hover:border-line-strong"
              >
                Sign out and discard
              </button>
              <button
                type="button"
                autoFocus
                onClick={() => setConfirmingSignOut(false)}
                className="ng-touch-target inline-flex items-center justify-center rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-ink transition-opacity hover:opacity-90"
              >
                Keep editing
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
