import { memo } from "react";

interface Option {
  id: string;
  name: string;
}

interface Props {
  label: string;
  /** Rendered before each name — "#" for channels, "@" for roles. */
  prefix: string;
  value: string[];
  options: Option[];
  error?: string;
  onChange: (value: string[]) => void;
}

/**
 * Pick several ids from a list. A select adds, a chip removes — the same shape
 * as BadwordsEditor, so every multi-value field on this screen reads the same.
 * Already-picked options leave the select, which stops the duplicates the
 * server would strip from being offered in the first place.
 */
// See the note in ChannelSelect.tsx — same shared-draft-object problem.
function IgnoreListEditor({
  label,
  prefix,
  value,
  options,
  error,
  onChange,
}: Props) {
  const byId = new Map(options.map((o) => [o.id, o]));
  const available = options.filter((o) => !value.includes(o.id));

  return (
    <div>
      <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">{label}</span>
      <select
        value=""
        disabled={available.length === 0}
        aria-label={`Add to ${label.toLowerCase()}`}
        aria-invalid={error ? true : undefined}
        onChange={(e) => {
          if (e.target.value) onChange([...value, e.target.value]);
        }}
        className={`mt-1.5 w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink disabled:opacity-50 ${
          error ? "border-primary" : "border-line"
        }`}
      >
        <option value="">{available.length === 0 ? "— all added —" : "— add one —"}</option>
        {available.map((o) => (
          <option key={o.id} value={o.id}>
            {prefix} {o.name}
          </option>
        ))}
      </select>
      {error && <p className="text-primary mt-1 text-xs">{error}</p>}
      {value.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {value.map((id) => {
            // An id with no option behind it is a channel or role deleted in
            // Discord since it was saved. Show the raw id rather than hiding
            // it, so it can be removed instead of lingering invisibly.
            const name = byId.get(id)?.name;
            return (
              <li
                key={id}
                className="flex max-w-full items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1 text-sm"
              >
                <span className="min-w-0 break-all">
                  {name ? `${prefix} ${name}` : `${id} (deleted)`}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${name ?? id}`}
                  onClick={() => onChange(value.filter((v) => v !== id))}
                  className="ng-icon-button -my-1 text-ink-muted transition-colors hover:text-ink"
                >
                  <span aria-hidden="true">×</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default memo(IgnoreListEditor);
