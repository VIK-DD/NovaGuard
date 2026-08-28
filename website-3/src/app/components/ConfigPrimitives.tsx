import { memo, useEffect, useId, useState } from "react";
import { Link } from "@tanstack/react-router";
import type { GuildSettings } from "../../lib/api/schemas";
import Icon, { type IconName } from "./Icon";
import {
  CONFIG_MODULES,
  isModuleActive,
  type ConfigModuleKey,
} from "../moduleCatalog";

// These small controls live outside GuildConfig so the screen can focus on
// orchestration. Memoization is useful because GuildConfig owns one settings
// object and otherwise re-renders every field after any edit.
export const Toggle = memo(function Toggle(props: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between border-t border-line py-4">
      <span className="text-sm">{props.label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={props.checked}
        aria-label={props.label}
        onClick={() => props.onChange(!props.checked)}
        className="ng-touch-target grid h-11 w-12 shrink-0 appearance-none place-items-center rounded-[8px] p-0"
      >
        <span
          aria-hidden="true"
          className={`relative block h-6 w-11 shrink-0 rounded-full border p-[2px] transition-[background-color,border-color] duration-150 ${
            props.checked ? "border-primary bg-primary" : "border-line-strong bg-card"
          }`}
        >
          <span
            className={`block h-[18px] w-[18px] rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.22)] transition-transform duration-150 ease-out ${
              props.checked ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </span>
      </button>
    </div>
  );
});

export const NumberField = memo(function NumberField(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix?: string;
  error?: string;
  onChange: (value: number) => void;
}) {
  // Preserve an editable string so a visitor can clear and retype the value
  // without the previous number snapping back after the first keystroke.
  const [text, setText] = useState(String(props.value));
  const [editing, setEditing] = useState(false);
  const inputId = useId();
  const errorId = `${inputId}-error`;

  useEffect(() => {
    if (!editing) setText(String(props.value));
  }, [editing, props.value]);

  return (
    <div className="block">
      <label htmlFor={inputId} className="text-xs tracking-[0.15em] text-ink-muted uppercase">
        {props.label}
        {props.suffix && <span className="normal-case"> ({props.suffix})</span>}
      </label>
      <input
        id={inputId}
        type="number"
        inputMode="numeric"
        min={props.min}
        max={props.max}
        value={text}
        aria-invalid={props.error ? true : undefined}
        aria-describedby={props.error ? errorId : undefined}
        onFocus={() => setEditing(true)}
        onChange={(event) => {
          setText(event.target.value);
          const parsed = Number(event.target.value);
          if (event.target.value !== "" && Number.isInteger(parsed)) props.onChange(parsed);
        }}
        onBlur={() => {
          setEditing(false);
          setText(String(props.value));
        }}
        className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
          props.error ? "border-primary" : "border-line"
        }`}
      />
      {props.error && (
        <p id={errorId} className="text-primary mt-1 text-xs">
          {props.error}
        </p>
      )}
    </div>
  );
});

export function Section(props: {
  id: ConfigModuleKey;
  icon: IconName;
  kicker: string;
  description: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      id={props.id}
      aria-labelledby={`${props.id}-title`}
      className="scroll-mt-6 rounded-[var(--radius-card)] border border-line bg-card p-5 shadow-[0_1px_0_hsl(0_0%_100%/0.03)_inset] sm:p-6"
    >
      <div className="flex items-start gap-3.5">
        <span className="bg-line/40 grid h-10 w-10 shrink-0 place-items-center rounded-[8px] border border-line text-ink">
          <Icon name={props.icon} size={20} />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p id={`${props.id}-title`} className="text-xs tracking-[0.2em] text-primary uppercase">
              {props.kicker}
            </p>
            <span
              className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                props.active
                  ? "border-good/35 bg-good/10 text-good"
                  : "border-line bg-bg-subtle text-ink-muted"
              }`}
            >
              {props.active ? "Active" : "Not configured"}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-muted">{props.description}</p>
        </div>
      </div>
      <div className="mt-6">{props.children}</div>
    </section>
  );
}

export function ModuleNav({ guildId, settings }: { guildId: string; settings: GuildSettings }) {
  return (
    <nav aria-label="Configuration modules" className="mt-8 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {CONFIG_MODULES.map((module) => {
        const active = isModuleActive(settings, module.key);
        return (
          <Link
            key={module.key}
            to="/g/$guildId/settings/$moduleId"
            params={{ guildId, moduleId: module.key }}
            className="ng-pressable group flex min-h-[5.5rem] items-start gap-3 rounded-[var(--radius-card)] border border-line bg-card p-4 transition-colors hover:border-line-strong"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[8px] border border-line bg-bg-subtle text-ink">
              <Icon name={module.icon} size={18} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{module.label}</span>
                <span
                  aria-label={active ? "Active" : "Not configured"}
                  className={`h-2 w-2 shrink-0 rounded-full ${active ? "bg-good" : "bg-line-strong"}`}
                />
              </span>
              <span className="mt-1 line-clamp-2 block text-xs leading-5 text-ink-muted">
                {module.description}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
