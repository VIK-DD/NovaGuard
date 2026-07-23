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
    <div
      data-savebar
      className="fixed inset-x-0 bottom-0 border-t border-line bg-background"
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4 sm:px-6">
        <p className={`truncate text-sm ${error ? "text-primary" : "text-ink-muted"}`}>
          {error ?? "Unsaved changes"}
        </p>
        <div className="flex shrink-0 items-center justify-end gap-3">
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
            className="bg-primary rounded-full px-5 py-2 text-sm text-primary-ink transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
