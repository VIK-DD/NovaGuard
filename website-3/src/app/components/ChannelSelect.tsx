import { useMemo } from "react";
import type { GuildChannel } from "../../lib/api/schemas";

interface Props {
  label: string;
  value: string | null;
  channels: GuildChannel[];
  error?: string;
  onChange: (value: string | null) => void;
}

export default function ChannelSelect({ label, value, channels, error, onChange }: Props) {
  const groups = useMemo(() => {
    const map = new Map<string, GuildChannel[]>();
    for (const c of channels) {
      const key = c.category ?? "No category";
      const list = map.get(key) ?? [];
      list.push(c);
      map.set(key, list);
    }
    return [...map.entries()];
  }, [channels]);

  return (
    <label className="block">
      <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        aria-invalid={error ? true : undefined}
        className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
          error ? "border-primary" : "border-line"
        }`}
      >
        <option value="">— none —</option>
        {groups.map(([category, list]) => (
          <optgroup key={category} label={category}>
            {list.map((c) => (
              <option key={c.id} value={c.id}>
                # {c.name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {error && <p className="text-primary mt-1 text-xs">{error}</p>}
    </label>
  );
}
