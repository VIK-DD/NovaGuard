import { useState } from "react";
import { normalizeBadwords } from "../lib/configForm";

interface Props {
  value: string[];
  error?: string;
  onChange: (value: string[]) => void;
}

export default function BadwordsEditor({ value, error, onChange }: Props) {
  const [input, setInput] = useState("");

  const add = () => {
    if (!input.trim()) return;
    onChange(normalizeBadwords([...value, ...input.split(",")]));
    setInput("");
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
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder="Type a word, press Enter"
          aria-label="Add blocked word"
          className={`w-full rounded-md border bg-card px-3 py-2 text-sm outline-none focus:border-ink ${
            error ? "border-primary" : "border-line"
          }`}
        />
        <button
          type="button"
          onClick={add}
          className="shrink-0 rounded-md border border-line px-4 py-2 text-sm transition-colors hover:border-ink sm:py-0"
        >
          Add
        </button>
      </div>
      {error && <p className="text-primary mt-1 text-xs">{error}</p>}
      {value.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {value.map((word) => (
            <li
              key={word}
              className="flex max-w-full items-center gap-1.5 rounded-md border border-line bg-card px-2 py-0.5 text-sm"
            >
              <code className="min-w-0 break-all">{word}</code>
              <button
                type="button"
                aria-label={`Remove ${word}`}
                onClick={() => onChange(value.filter((w) => w !== word))}
                className="text-ink-muted transition-colors hover:text-ink"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
