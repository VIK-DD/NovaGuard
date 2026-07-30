interface Props {
  visible: boolean;
  saving: boolean;
  /** True for a few seconds right after a successful save — see GuildConfig.tsx. */
  saved: boolean;
  error?: string;
  onSave: () => void;
  onDiscard: () => void;
}

export default function SaveBar({ visible, saving, saved, error, onSave, onDiscard }: Props) {
  const shown = visible || saved || Boolean(error);
  // `visible` wins over `saved`: resuming an edit while the "Saved" toast is
  // still fading out must read as "Unsaved changes" immediately, not wait out
  // the toast's timer.
  const message = error ?? (visible ? "Unsaved changes" : saved ? "Saved" : "");

  return (
    <div
      data-savebar
      aria-hidden={!shown}
      // Always mounted (a `fixed` bar costs nothing hidden) so the hide
      // transition can actually play — the old `return null` on !visible
      // cut the bar on the same frame the save request resolved, which is
      // what read as abrupt rather than "smooth".
      className={`fixed inset-x-0 bottom-0 z-20 border-t border-line bg-background transition-[translate,opacity] duration-[260ms] ease-[cubic-bezier(0.16,1,0.3,1)] ${
        shown ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-2 opacity-0"
      }`}
    >
      <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4 sm:px-6">
        <p
          className={`truncate text-sm ${error ? "text-primary" : saved && !visible ? "text-good" : "text-ink-muted"}`}
        >
          {message}
        </p>
        {(visible || error) && (
          <div className="flex shrink-0 items-center justify-end gap-3">
            <button
              type="button"
              onClick={onDiscard}
              disabled={saving}
              className="ng-touch-target inline-flex items-center text-sm text-ink-muted transition-colors hover:text-ink disabled:opacity-50"
            >
              Discard
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={saving || !visible}
              className="ng-touch-target inline-flex items-center bg-primary rounded-full px-5 py-2 text-sm text-primary-ink transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
