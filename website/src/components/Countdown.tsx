import { useEffect, useRef, useState } from "react";

type Parts = { days: number; hours: number; minutes: number; seconds: number };

function partsUntil(target: Date): Parts | null {
  const diff = target.getTime() - Date.now();
  if (diff <= 0) return null;
  const total = Math.floor(diff / 1000);
  return {
    days: Math.floor(total / 86400),
    hours: Math.floor((total % 86400) / 3600),
    minutes: Math.floor((total % 3600) / 60),
    seconds: total % 60,
  };
}

function Cell({ value, label, wide }: { value: number; label: string; wide?: boolean }) {
  const text = String(value).padStart(wide ? 3 : 2, "0");
  return (
    <div className="cd-cell">
      {/* key remounts the span on change so the tick animation replays */}
      <span className="cd-value" key={text}>
        {text}
      </span>
      <span className="cd-label">{label}</span>
    </div>
  );
}

export default function Countdown({ target, onZero }: { target: Date; onZero: () => void }) {
  const [parts, setParts] = useState<Parts | null>(() => partsUntil(target));
  const firedRef = useRef(false);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const next = partsUntil(target);
      setParts(next);
      if (next === null && !firedRef.current) {
        firedRef.current = true;
        onZero();
      }
    }, 250);
    return () => window.clearInterval(interval);
  }, [target, onZero]);

  if (parts === null) {
    return (
      <div className="cd-live" role="status">
        <span className="cd-live-dot" aria-hidden="true" />
        IT&rsquo;S LIVE
      </div>
    );
  }

  return (
    <div
      className="countdown"
      role="timer"
      aria-label={`${parts.days} days, ${parts.hours} hours, ${parts.minutes} minutes and ${parts.seconds} seconds until launch`}
    >
      <Cell value={parts.days} label="days" wide />
      <span className="cd-sep" aria-hidden="true">
        :
      </span>
      <Cell value={parts.hours} label="hours" />
      <span className="cd-sep" aria-hidden="true">
        :
      </span>
      <Cell value={parts.minutes} label="minutes" />
      <span className="cd-sep" aria-hidden="true">
        :
      </span>
      <Cell value={parts.seconds} label="seconds" />
    </div>
  );
}
