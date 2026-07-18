interface Props {
  visible: boolean;
  saving: boolean;
  error?: string;
  onSave: () => void;
  onDiscard: () => void;
}

export default function SaveBar({ visible, saving, error, onSave, onDiscard }: Props) {
  if (!visible && !error) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 border-t border-line bg-paper/95 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3">
        <p className={`truncate text-sm ${error ? "text-accent" : "text-ink-muted"}`}>
          {error ?? "Unsaved changes"}
        </p>
        <div className="flex shrink-0 items-center gap-3">
          <button
            type="button"
            onClick={onDiscard}
            disabled={saving}
            className="text-sm text-ink-muted transition-colors hover:text-ink disabled:opacity-50"
          >
            Discard
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={saving || !visible}
            className="bg-accent rounded-full px-5 py-2 text-sm text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
