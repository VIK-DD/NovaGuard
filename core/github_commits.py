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


# ── watching every branch, not only the default one ───────────────────


def branches_needing_a_read(branches, seen_shas):
    """Which branches have moved since the last poll.

    GitHub has no endpoint for "every commit on every branch", so each branch
    costs its own request. The branch listing already carries each head SHA,
    though, so a branch whose head is already known cannot be hiding anything
    new and is skipped entirely. A quiet repository therefore costs one
    request per poll however many branches it has.
    """
    seen = set(seen_shas or ())
    moved = []
    for branch in branches or []:
        name = (branch or {}).get("name")
        head = ((branch or {}).get("commit") or {}).get("sha")
        if name and head and head not in seen:
            moved.append(name)
    return moved


def stored_shas(state):
    """Read the remembered SHAs, telling an old state file from a new one.

    Before branches were watched this was a bare list covering the default
    branch only. Reading that as a complete picture would make every other
    branch look brand new on the first poll after an upgrade, and announce
    months-old commits from stale branches as if they had just landed. A
    dict is the new shape; anything else means "prime, say nothing".
    """
    if isinstance(state, dict):
        return list(state.get("seen") or []), False
    return [], True


def store_shas(shas):
    """The shape stored_shas recognises as already branch-aware."""
    return {"seen": list(shas)}


def remember_across_branches(previous, *sha_groups, keep=300):
    """The rolling set of announced SHAs, newest first.

    Wider than the single-branch window because several branches share it: a
    SHA that falls off the end is announced again the next time its branch is
    read, so the window has to outlast the busiest stretch the poll interval
    can cover.
    """
    ordered = []
    for group in (*sha_groups, previous or ()):
        for sha in group or ():
            if sha and sha not in ordered:
                ordered.append(sha)
    return ordered[:keep]


def merge_new_commits(per_branch, seen_shas, *, limit=MAX_ANNOUNCED):
    """Flatten several branches' commits into one announcement.

    The same commit genuinely exists on several branches — pushing a working
    branch and then main is one commit on two of them — and nobody wants to
    read about it twice. What prevents that is the growing ``seen`` set: each
    branch is walked against everything already picked, and select_new_commits
    stops at the first SHA it recognises, so a shared commit ends the second
    branch's walk before it can be added again.

    (An explicit "skip if already picked" check used to sit in the loop below.
    Mutation testing showed removing it changed nothing, because it could
    never fire for exactly the reason above. Dead code that implies a case
    which cannot happen is worse than no code, so it is gone.)

    The branch credited is whichever is walked first, so callers pass the
    default branch ahead of the rest.
    """
    seen = set(seen_shas or ())
    picked = []
    for branch_name, commits in per_branch:
        for commit in select_new_commits(commits, seen, limit=None):
            seen.add(commit_sha(commit))
            picked.append((branch_name, commit))
    return picked[-limit:] if limit else picked
