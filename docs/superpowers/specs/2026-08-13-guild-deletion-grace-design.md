# Guild Deletion Grace Period — Design

**Date:** 2026-08-13
**Status:** Approved

## Problem

`cogs/privacy.py` erases every record a server has the instant NovaGuard leaves it:

```python
@commands.Cog.listener()
async def on_guild_remove(self, guild):
    await erase_live_guild_data(self.bot, guild.id)
```

Two distinct failures follow from that one line.

**Accidental loss.** An accidental kick, a permission change that evicts the bot,
or a moderator tidying roles destroys settings, levels, economy, tickets and
warnings with no undo. The erasure also writes a deletion-ledger entry, so
restoring a backup deliberately will not bring the data back — the ledger scrubs
it again on restore. The loss is total and by design.

**Sabotage.** Anyone able to kick the bot can irreversibly erase a community's
entire history. Removal is not authenticated as a deletion request, but it is
treated as one.

GDPR does not require immediate erasure. Article 17 turns on data no longer
being necessary for its purpose; a bounded grace window before erasure is
compatible with that and is what comparable bots do.

## Solution

Removal schedules a deletion 30 days out instead of performing one. Re-adding
the bot cancels it. A daily loop erases whatever has actually expired.

During the window the data is retained but not processed: no gateway events
arrive, no commands run, and `core/webserver.py:918` already returns 404 for any
guild the bot is not in. Nothing extra is needed to stop processing — absence
does it.

Explicit deletion through `/privacy server-delete` stays immediate. That request
is authenticated (owner-only, typed confirmation) and must not be softened.

## Architecture

A new module, `core/guild_grace.py`, owns the marker lifecycle.

It is separate from `core/privacy.py` because that file is already 746 lines
with a coherent job — export, erasure, retention. Grace scheduling is a distinct
responsibility with its own table and its own failure modes. Split, each file
stays small enough to hold in context while editing.

Imports run one way only: `guild_grace` depends on `core.database` and on
`core.privacy` for the configured window. Neither depends on `guild_grace`. The
erasure of due guilds lives in the cog, which is the only layer holding the
`bot` object needed to clear feature caches.

### Schema

Added to `init_database()` in `core/database.py`, following the existing
`CREATE TABLE IF NOT EXISTS` pattern. No migration step is required.

```sql
CREATE TABLE IF NOT EXISTS pending_guild_deletions (
    guild_id     TEXT PRIMARY KEY,
    scheduled_at TEXT NOT NULL,
    deadline     TEXT NOT NULL
)
```

`guild_id` as primary key makes contradictory rows for one server impossible
across any sequence of removals and re-adds.

The table is included in backups, so a restore stays consistent with the state
that produced it. It is also added to the table list scrubbed by
`core/privacy_ledger.py::_scrub_sqlite`, so restoring a snapshot cannot
reintroduce a stale marker for a guild that has since been erased for real.

### Configuration

`PRIVACY_GUILD_GRACE_DAYS` joins `RETENTION_DEFAULTS` in `core/privacy.py`,
defaulting to `30`. It inherits the existing `_retention_value` bounding — an
integer clamped to 1..3650, falling back to the default on malformed input — and
appears in the report `run_retention_cleanup` returns, so its live value is
visible in logs without new code.

### Module interface

```python
GRACE_DAYS_KEY = "PRIVACY_GUILD_GRACE_DAYS"

def grace_days(env=None) -> int
def schedule_guild_deletion(guild_id, *, now=None, env=None) -> dict
def cancel_guild_deletion(guild_id) -> bool
def pending_guild_deletions() -> list[dict]
def due_guild_deletions(*, now=None) -> list[str]
```

An earlier draft of this design also listed `clear_guild_deletion`, to be
called after a real erasure while `cancel_guild_deletion` handled a returning
server. Both would have had identical bodies. Two functions that differ only in
name are worse than one, and the distinction that mattered — why the row went
away — belongs in the caller's log line, which is where it now lives.

`schedule_guild_deletion` returns the stored row. Re-scheduling an already
pending guild leaves the original deadline untouched — a second removal must not
extend the window, or a repeated kick/re-add cycle could keep data alive
indefinitely.

`now` and `env` are injectable on every function that reads them, so tests never
depend on wall-clock time or process environment.

## Data flow

**Removal.** `on_guild_remove` calls `schedule_guild_deletion`. Nothing is
erased.

**Re-add.** `on_guild_join` calls `cancel_guild_deletion`. The data was never
touched, so the server resumes exactly where it left off.

**Daily loop.** `retention_loop` runs this order, and the order is load-bearing:

1. Reconcile markers against reality
2. Erase guilds whose deadline has passed
3. Existing retention cleanup
4. Ledger sync

Reconciliation before erasure closes the narrow case where a bot re-added on day
29.9 meets a loop that fires on day 30: reconciliation clears the marker before
step 2 can read it.

### Reconciliation

Runs at startup — `tasks.loop` executes its body immediately after
`before_loop` — and every 24 hours thereafter. It works in both directions:

- guild has stored settings, bot is not in it, no marker → **create marker**
- guild has a marker, bot **is** in it → **remove marker**

The second direction makes the system self-healing. If the Discord gateway ever
delivers a partial guild list on connect and a healthy server is marked, the
next healthy connect clears it. Only expiry at 30 days is irreversible; the
marker itself never is.

Reconciliation iterates `storage.all_guild_settings()`, which returns only
guilds that have stored settings. A guild already erased does not appear there
and therefore cannot be re-marked.

## Explicit deletion guard

`/privacy server-delete` erases, then calls `guild.leave()`, which fires
`on_guild_remove`. Without a guard, an intentional deletion would be converted
into a pending one — the opposite of what the owner asked for.

The cog keeps a set of guild ids erased on purpose, populated immediately before
`guild.leave()` and consumed by `on_guild_remove`. Both run on the event loop,
so there is no race.

If the bot restarts between `leave()` and the event and the set is lost, the
guild has no stored settings, so reconciliation does not see it either. The case
is covered from two independent directions.

## Error handling

Both paths fail toward retaining data, never toward deleting it.

- A failed erasure for one due guild must not abort the loop for the rest. Each
  guild is wrapped individually and reported through `send_error_digest`.
- If writing the marker fails during `on_guild_remove`, the guild keeps its data
  and reconciliation retries on the next startup or daily tick.

Both scheduling and expiry write a line to stdout, visible in `pm2 logs`. That
is the whole operator surface: no new command, no DM, no dashboard panel.

## Testing

**`tests/test_guild_grace.py`** — module level, against a temporary database:

- scheduling stores the row with a deadline exactly `grace_days` after `now`
- re-scheduling a pending guild preserves the original deadline
- cancelling removes the row and reports whether one existed
- `due_guild_deletions` returns only guilds past an injected `now`
- a malformed `PRIVACY_GUILD_GRACE_DAYS` falls back to 30
- the value is clamped to the 1..3650 bounds

**`tests/test_privacy_grace_flow.py`** — cog behaviour with a stub bot:

- `on_guild_remove` schedules and erases nothing
- a guild in the explicit-deletion set is not scheduled
- `on_guild_join` cancels a pending marker
- reconciliation marks a guild with settings the bot is absent from
- reconciliation clears the marker for a guild the bot is present in
- an expired guild is erased and receives a deletion-ledger entry
- one guild raising during erasure does not prevent the next from being erased

## Published policy

Code and published policy must not contradict each other. Three places change:

- `RETENTION_ROWS` in `website-3/src/data/privacy.ts` — a row stating that
  server data is erased 30 days after removal unless the bot is added back
- the processing register table in `docs/PRIVACY-OPERATIONS.md`
- step 6 of the individual-rights procedure in the same document

## Out of scope

No new command, no DM notification, and no change to `/privacy server-delete`,
`/privacy delete`, or user-scoped erasure. Operator visibility is console logs
only, chosen deliberately over an `/admin` listing to keep the surface minimal.
