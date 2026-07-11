import { useEffect, useState } from "react";
import Starfield from "./components/Starfield";
import NovaTitle from "./components/NovaTitle";
import Countdown from "./components/Countdown";
import ThemeToggle from "./components/ThemeToggle";

export type Theme = "dark" | "light";

/** Midnight, September 1st 2026, Europe/Bucharest (EEST, UTC+3). */
export const LAUNCH_AT = new Date("2026-08-31T21:00:00Z");

function initialTheme(): Theme {
  try {
    return localStorage.getItem("ng-theme") === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [launched, setLaunched] = useState(() => Date.now() >= LAUNCH_AT.getTime());

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("ng-theme", theme);
    } catch {
      /* private mode — theme just won't persist */
    }
  }, [theme]);

  return (
    <div className="scene">
      <div className="aurora aurora-a" aria-hidden="true" />
      <div className="aurora aurora-b" aria-hidden="true" />
      <Starfield theme={theme} />

      <header className="top-bar">
        <span className="brand-mark">NG</span>
        <ThemeToggle theme={theme} onChange={setTheme} />
      </header>

      <main className="core">
        <p className="eyebrow">
          <span className="eyebrow-rule" aria-hidden="true" />
          {launched ? "Nova Project · now live" : "Nova Project · ignition 01.09.2026"}
          <span className="eyebrow-rule" aria-hidden="true" />
        </p>

        <NovaTitle launched={launched} />

        <p className="subtitle">
          {launched ? (
            <>
              The counter hit zero. <strong>Welcome to Nova Project.</strong>
            </>
          ) : (
            <>
              The guardian of <strong>Cloud &amp; Friends</strong> is being reforged.
              When the counter hits zero, everything changes.
            </>
          )}
        </p>

        <Countdown target={LAUNCH_AT} onZero={() => setLaunched(true)} />
      </main>

      <footer className="foot">
        <a
          className="foot-link"
          href="https://github.com/VIK-DD/NovaGuard"
          target="_blank"
          rel="noreferrer"
        >
          GitHub
        </a>
        <span className="foot-sep" aria-hidden="true">
          ✦
        </span>
        <span className="foot-note">© 2026 VIK-DD — built among the stars</span>
      </footer>
    </div>
  );
}
