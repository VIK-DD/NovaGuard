import type { Theme } from "../App";

export default function ThemeToggle({
  theme,
  onChange,
}: {
  theme: Theme;
  onChange: (theme: Theme) => void;
}) {
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      className="theme-toggle"
      role="switch"
      aria-checked={isDark}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => onChange(isDark ? "light" : "dark")}
    >
      <span className="toggle-track" aria-hidden="true">
        <span className="toggle-star s1" />
        <span className="toggle-star s2" />
        <span className="toggle-star s3" />
        <span className="toggle-knob">
          {isDark ? (
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <path
                d="M20.4 14.2A8.5 8.5 0 0 1 9.8 3.6a8.5 8.5 0 1 0 10.6 10.6Z"
                fill="currentColor"
              />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <circle cx="12" cy="12" r="4.4" fill="currentColor" />
              <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                <path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5 5l1.7 1.7M17.3 17.3 19 19M19 5l-1.7 1.7M6.7 17.3 5 19" />
              </g>
            </svg>
          )}
        </span>
      </span>
    </button>
  );
}
