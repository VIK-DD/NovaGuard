import { useParams } from "@tanstack/react-router";
import { useAudit } from "../queries";

const dateFmt = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export default function AuditLog() {
  const { guildId } = useParams({ strict: false }) as { guildId: string };
  const audit = useAudit(guildId);

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <p className="text-xs tracking-[0.25em] text-ink-muted uppercase">Dashboard changes</p>

      {audit.isPending && (
        <div className="mt-6" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse border-t border-line py-4">
              <div className="h-5 w-2/3 rounded bg-line/60" />
            </div>
          ))}
        </div>
      )}

      {audit.isError && (
        <p className="mt-6 border-t border-line pt-4 text-sm text-ink-muted">
          Could not load the audit log.{" "}
          <button onClick={() => void audit.refetch()} className="underline hover:text-ink">
            Try again
          </button>
        </p>
      )}

      {audit.data && audit.data.audit.length === 0 && (
        <p className="mt-6 border-t border-line pt-4 text-sm text-ink-muted">
          No dashboard changes yet.
        </p>
      )}

      {audit.data && audit.data.audit.length > 0 && (
        <ul className="mt-6">
          {audit.data.audit.map((entry, i) => (
            <li key={`${entry.created_at}-${i}`} className="border-t border-line py-4">
              <div className="flex items-baseline justify-between gap-4">
                <p className="text-sm">
                  <strong>{entry.username}</strong>{" "}
                  <span className="text-xs tracking-[0.15em] text-ink-muted uppercase">
                    {entry.action.replaceAll("_", " ")}
                  </span>
                </p>
                <time className="shrink-0 text-xs text-ink-muted">
                  {dateFmt.format(new Date(entry.created_at))}
                </time>
              </div>
              {Object.keys(entry.changes).length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-2">
                  {Object.entries(entry.changes).map(([key, value]) => (
                    <li key={key}>
                      <code className="rounded-md border border-line bg-surface px-2 py-0.5 text-xs">
                        {key} → {value === null ? "none" : String(value)}
                      </code>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
