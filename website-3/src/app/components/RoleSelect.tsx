import type { GuildRole } from "../../lib/api/schemas";

interface Props {
  label: string;
  value: string | null;
  roles: GuildRole[];
  error?: string;
  onChange: (value: string | null) => void;
}

export default function RoleSelect({ label, value, roles, error, onChange }: Props) {
  const selected = roles.find((r) => r.id === value);

  return (
    <label className="block">
      <span className="flex items-center gap-2 text-xs tracking-[0.15em] text-ink-muted uppercase">
        {label}
        {selected && (
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-2.5 rounded-full border border-line"
            style={{ backgroundColor: selected.color }}
          />
        )}
      </span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        aria-invalid={error ? true : undefined}
        className={`mt-1.5 w-full rounded-md border bg-surface px-3 py-2 text-sm outline-none focus:border-ink ${
          error ? "border-accent" : "border-line"
        }`}
      >
        <option value="">— none —</option>
        {roles.map((r) => (
          <option key={r.id} value={r.id}>
            @ {r.name}
          </option>
        ))}
      </select>
      {error && <p className="text-accent mt-1 text-xs">{error}</p>}
    </label>
  );
}
