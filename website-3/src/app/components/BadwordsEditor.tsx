import { memo, useState } from "react";
import { normalizeBadwords } from "../lib/configForm";

interface Props {
  value: string[];
  error?: string;
  onChange: (value: string[]) => void;
}

// See the note in ChannelSelect.tsx — same shared-draft-object problem.
function BadwordsEditor({ value, error, onChange }: Props) {
  const [input, setInput] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);

  const add = () => {
    if (!input.trim()) return;
    if (value.length >= 100) {
      setInputError("You can block at most 100 words.");
      return;
    }
    const next = normalizeBadwords([...value, ...input.split(",")]);
    if (next.length === value.length) {
      setInputError("That word is already in the list.");
      return;
    }
    onChange(next);
    setInput("");
    setInputError(null);
  };

  return (
    <div>
      <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
        Blocked words
      </span>
      <div className="mt-1.5 flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setInputError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={value.length >= 100 ? "100-word limit reached" : "Type a word, press Enter"}
          aria-label="Add blocked word"
          aria-invalid={error || inputError ? true : undefined}
          className={`w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
            error || inputError ? "border-primary" : "border-line"
          }`}
        />
        <button
          type="button"
          onClick={add}
          disabled={!input.trim() || value.length >= 100}
          className="ng-touch-target flex shrink-0 items-center justify-center rounded-md border border-line px-4 py-2 text-sm transition-colors hover:border-ink disabled:opacity-50 sm:py-0"
        >
          Add
        </button>
      </div>
      {error && <p className="text-primary mt-1 text-xs">{error}</p>}
      {!error && inputError && <p className="text-primary mt-1 text-xs">{inputError}</p>}
      {value.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {value.map((word) => (
            <li
              key={word}
              className="flex max-w-full items-center gap-1.5 rounded-md border border-line bg-card px-2 py-1 text-sm"
            >
              <code className="min-w-0 break-all">{word}</code>
              <button
                type="button"
                aria-label={`Remove ${word}`}
                onClick={() => onChange(value.filter((w) => w !== word))}
                className="ng-icon-button -my-1 text-ink-muted transition-colors hover:text-ink"
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default memo(BadwordsEditor);
