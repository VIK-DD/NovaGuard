"""Deciding which commits are new, without announcing one twice.

The watcher used to learn about pushes from /events, which is a timeline
GitHub serves from a cache and documents as unsuitable for anything
real-time. Measured on 2026-08-19 it was a full day behind: commits existed
on main at 20:42 while the newest event returned was from the previous
evening at 21:30. Nothing was broken in the bot; the source simply had not
caught up. /commits is current, so pushes are read from there instead.

The awkward part is that /commits is a list, not a stream: every poll returns
the same newest commits again. Working out which of them have not been
announced is the whole job, and it is arithmetic over two sets, so it lives
here where it can be tested without a network.
"""

MAX_ANNOUNCED = 5


def commit_sha(commit):
    return (commit or {}).get("sha") or ""


def select_new_commits(commits, seen_shas, *, limit=MAX_ANNOUNCED):
    """The commits worth announcing, oldest first.

    Oldest first because they are posted in order, and a channel that reads
    newest-at-the-top is confusing to scroll back through.

    A commit already announced stops the walk. GitHub returns newest first, so
    everything past the first familiar SHA has been seen as well — and judging
    them individually would re-announce a commit whose SHA had aged out of the
    remembered window, which is exactly how a channel fills with duplicates
    after a restart.
    """
    seen = set(seen_shas or ())
    fresh = []
    for commit in commits or []:
        sha = commit_sha(commit)
        if not sha or sha in seen:
            break
        fresh.append(commit)
    fresh.reverse()
    return fresh[-limit:] if limit else fresh


def remembered_shas(commits, *, keep=40):
    """What to store, so the window outlives a quiet weekend.

    Keeping more than one poll's worth guards the case where several commits
    land between two passes: with only the newest remembered, the ones beneath
    it would look new again on the following one.
    """
    shas = [commit_sha(commit) for commit in commits or []]
    return [sha for sha in shas if sha][:keep]


def hidden_count(commits, seen_shas, *, limit=MAX_ANNOUNCED):
    """How many new commits are being left out of the announcement."""
    total = len(select_new_commits(commits, seen_shas, limit=None))
    return max(total - limit, 0)
