#!/usr/bin/env python3
"""Synchronize the content repo: pull (rebase) -> commit -> push, best-effort.

Ports neverland's strategy (``neverland/core/vcs.py``): the local commit is
always immediate, never deferred, and only the *network* half is allowed to
fail. Offline therefore degrades to "committed locally, will push later"
instead of losing the write.

Consecutive edits fold into a single commit by amending it, for as long as that
commit is young, ours and unpushed (see :func:`_open_batch`). What is
deliberately *not* done is deferring the write: the working tree is clean after
every call, so the editor, this script and the site never fight over the repo.
Only the history is compacted.

    sync.py                     # pull, commit, push (best-effort)
    sync.py --local             # commit only, no network
    sync.py -m "edit dev/…"     # custom commit message
    sync.py flush               # push pending commits (used by the web editor)

Stdlib only, like the rest of ``scripts/``.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from avallon.notes import config as cc

NET_TIMEOUT = 20  # seconds, for pull/push

# Marks a commit as written by this script, hence safe to amend. A commit the
# user wrote by hand in the content repo has no trailer and is never rewritten.
BATCH_TRAILER = "avallon-batch"

# How long consecutive edits keep folding into the same commit. Saving a page
# twelve times in ten minutes should read as one change, not twelve.
DEFAULT_WINDOW = 900  # 15 minutes
WINDOW_ENV = "AVALLON_SYNC_WINDOW"


def sync_window() -> int:
    """Return the batching window in seconds (0 disables batching)."""
    raw = os.environ.get(WINDOW_ENV)
    if raw is None:
        return DEFAULT_WINDOW
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_WINDOW


# --------------------------------------------------------------------------- #
# Git primitives                                                              #
# --------------------------------------------------------------------------- #


def run_git(
    args: list[str],
    cwd: Path | None = None,
    *,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Run a git command and capture its output.

    Parameters
    ----------
    args : list of str
        Git arguments, without the leading ``git``.
    cwd : pathlib.Path, optional
        Repository directory, passed as ``git -C <cwd>``.
    timeout : int, optional
        Timeout in seconds.

    Returns
    -------
    subprocess.CompletedProcess
        The completed process, with captured text output.
    """
    cmd = ["git"]
    if cwd is not None:
        cmd += ["-C", str(cwd)]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def is_git_repo(path: Path) -> bool:
    """Return whether *path* is inside a git work tree."""
    if not path.exists():
        return False
    res = run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    return res.returncode == 0 and res.stdout.strip() == "true"


def has_origin(path: Path) -> bool:
    """Return whether an ``origin`` remote is configured."""
    return run_git(["remote", "get-url", "origin"], cwd=path).returncode == 0


def has_upstream(path: Path) -> bool:
    """Return whether the current branch tracks an upstream branch."""
    args = ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
    return run_git(args, cwd=path).returncode == 0


def is_repo_root(content_dir: Path) -> bool:
    """Return whether *content_dir* is the root of its git work tree.

    Two things hang off this. Amending without a pathspec is the only safe way
    to amend, so batching is disabled when the content dir is nested inside
    another repo. And at the root the commit can be index-based, which is what
    lets the ``pre-commit`` date hook re-stage the files it stamps: with a
    pathspec, git commits from a temporary index and leaves the real one stale
    (``git status`` then reports phantom modifications until the next ``add``).
    """
    res = run_git(["rev-parse", "--show-toplevel"], cwd=content_dir)
    if res.returncode != 0 or not res.stdout.strip():
        return False
    return Path(res.stdout.strip()) == content_dir.resolve()


def unpushed_count(content_dir: Path) -> int:
    """Return the number of local commits not yet pushed (0 without upstream)."""
    if not has_upstream(content_dir):
        return 0
    res = run_git(["rev-list", "--count", "@{u}..HEAD"], cwd=content_dir)
    try:
        return int(res.stdout.strip())
    except ValueError:
        return 0


def has_commits(content_dir: Path) -> bool:
    """Return whether the repo has at least one commit."""
    return run_git(["rev-parse", "--verify", "HEAD"], cwd=content_dir).returncode == 0


def has_pending(content_dir: Path) -> bool:
    """Return whether commits exist locally that the remote does not have.

    A repo whose origin was added *after* its first commit has no upstream and
    therefore no computable ahead-count, yet everything in it is pending. Left
    to ``unpushed_count`` alone that reads as zero, and a sync with nothing new
    to commit would never push: the very first push would never happen.
    """
    if not has_commits(content_dir):
        return False
    return not has_upstream(content_dir) or unpushed_count(content_dir) > 0


# --------------------------------------------------------------------------- #
# Commit batching                                                             #
# --------------------------------------------------------------------------- #


def _batch_message(entries: list[str]) -> str:
    """Render the commit message recording *entries*."""
    if len(entries) == 1:
        parts = [entries[0]]
    else:
        parts = [
            f"batch: {len(entries)} changes",
            "\n".join(f"- {entry}" for entry in entries),
        ]
    parts.append(f"{BATCH_TRAILER}: {len(entries)}")
    return "\n\n".join(parts) + "\n"


def _parse_batch(message: str) -> list[str] | None:
    """Return the entries recorded in a batch message, or ``None``.

    The trailer is what identifies a commit as ours, so a hand-written commit
    in the content repo is never a candidate for rewriting.
    """
    lines = message.strip().splitlines()
    count: int | None = None
    for line in reversed(lines):
        if line.startswith(f"{BATCH_TRAILER}:"):
            try:
                count = int(line.split(":", 1)[1])
            except ValueError:
                return None
            break
    if count is None or count < 1:
        return None
    if count == 1:
        return lines[:1]
    return [line[2:] for line in lines if line.startswith("- ")] or None


def _head_age(content_dir: Path) -> float:
    """Return the age in seconds of HEAD, measured on its *author* date.

    The author date survives a rebase, so a batch opened at 09:00 still closes
    fifteen minutes later even if a pull rebased it in between. Amending only
    moves the committer date, which is what anchors the window on the batch's
    first edit rather than on its latest one.
    """
    res = run_git(["log", "-1", "--format=%at"], cwd=content_dir)
    try:
        return time.time() - int(res.stdout.strip())
    except ValueError:
        return float("inf")  # no commit yet


def _open_batch(content_dir: Path, window: int) -> list[str] | None:
    """Return the entries of HEAD while it is a batch still open for amending.

    A batch is open while it is younger than *window* seconds, carries our
    trailer, and has never been pushed. Anything else yields ``None`` and the
    caller writes a fresh commit.
    """
    if _head_age(content_dir) >= window:
        return None
    if has_upstream(content_dir) and unpushed_count(content_dir) == 0:
        return None  # HEAD is already on the remote: never rewrite it
    res = run_git(["log", "-1", "--format=%B"], cwd=content_dir)
    if res.returncode != 0:
        return None
    return _parse_batch(res.stdout)


def _write_commit(
    content_dir: Path, message: str, window: int
) -> subprocess.CompletedProcess:
    """Commit what is staged, folding it into HEAD while a batch is open.

    With batching off the message is written verbatim and carries no trailer,
    so a commit made outside a window is never amended later.
    """
    if not is_repo_root(content_dir):
        # Nested repo: scope the commit so the parent is never swept in. The
        # pathspec costs a stale index, which the next `add -A` refreshes.
        return run_git(["commit", "-m", message, "--", "."], cwd=content_dir)
    if window <= 0:
        return run_git(["commit", "-m", message], cwd=content_dir)

    # The lock is what makes the rewrite safe: a flush that might be pushing
    # HEAD right now holds it, and we then open a new batch rather than wait
    # (a save must stay instant).
    with sync_lock(content_dir) as acquired:
        entries = _open_batch(content_dir, window) if acquired else None
        if entries is not None:
            return run_git(
                ["commit", "--amend", "-m", _batch_message([*entries, message])],
                cwd=content_dir,
            )
    return run_git(["commit", "-m", _batch_message([message])], cwd=content_dir)


def commit_scoped(
    content_dir: Path, message: str, *, attempts: int = 3, window: int = 0
) -> tuple[bool, str]:
    """Stage and commit the content dir only, never an enclosing repo.

    ``add`` is always scoped with ``-- .`` (from ``cwd=content_dir``): if the
    content repo sits inside another one, nothing outside it is ever staged. A
    concurrent background sync may briefly hold ``index.lock``, so the commit
    is retried rather than failing loudly.

    Parameters
    ----------
    content_dir : pathlib.Path
        Content repo root.
    message : str
        Commit message.
    attempts : int, optional
        Number of tries on ``index.lock`` contention.
    window : int, optional
        Batching window in seconds (0 means one commit per call).

    Returns
    -------
    tuple of (bool, str)
        Whether a commit was created, and the last error message (empty on
        success or when there was nothing to commit).
    """
    last_err = ""
    for attempt in range(attempts):
        run_git(["add", "-A", "--", "."], cwd=content_dir)
        staged = run_git(["diff", "--cached", "--quiet", "--", "."], cwd=content_dir)
        if staged.returncode == 0:
            return False, ""  # nothing to commit
        res = _write_commit(content_dir, message, window)
        if res.returncode == 0:
            return True, ""
        last_err = res.stderr.strip()
        if attempt < attempts - 1:
            time.sleep(0.15)
    return False, last_err


# --------------------------------------------------------------------------- #
# Locking                                                                     #
# --------------------------------------------------------------------------- #


def _state_path(content_dir: Path, name: str) -> Path:
    """Return a state file path (lock/log) inside ``.git``, off the work tree."""
    res = run_git(["rev-parse", "--absolute-git-dir"], cwd=content_dir)
    base = (
        Path(res.stdout.strip())
        if res.returncode == 0 and res.stdout.strip()
        else content_dir
    )
    return base / name


@contextmanager
def sync_lock(content_dir: Path, *, blocking: bool = False):
    """Inter-process lock serializing synchronizations.

    Parameters
    ----------
    content_dir : pathlib.Path
        Content repo root.
    blocking : bool, optional
        When ``False`` (default), yield ``False`` at once if the lock is held;
        the caller gives up, since the running sync pushes pending commits
        anyway. When ``True``, wait for it.

    Yields
    ------
    bool
        Whether the lock was acquired.
    """
    handle = open(_state_path(content_dir, "avallon-sync.lock"), "w")
    try:
        flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except OSError:
            yield False
            return
        yield True
    finally:
        handle.close()


# --------------------------------------------------------------------------- #
# Synchronization                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class SyncResult:
    """Outcome of :func:`sync`.

    Attributes
    ----------
    committed : bool
        A commit was created.
    pushed : bool
        A push succeeded.
    pulled : bool
        A pull succeeded.
    held : bool
        The push was withheld because HEAD is still open for batching; the
        next flush sends it.
    conflict_files : list of str
        Files left in conflict by a failed rebase.
    warnings : list of str
        Non-fatal issues, mostly network related.
    """

    committed: bool = False
    pushed: bool = False
    pulled: bool = False
    held: bool = False
    conflict_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _default_message() -> str:
    return f"sync {socket.gethostname()} {datetime.now():%Y-%m-%dT%H:%M:%S}"


def _first_line(stderr: str, fallback: str) -> str:
    """Return git's first error line. Its network failures span several lines
    of advice, which turns a one-line summary into a wall of text."""
    for line in stderr.splitlines():
        if line.strip():
            return line.strip()
    return fallback


def sync(
    content_dir: Path,
    *,
    message: str | None = None,
    push_if_unchanged: bool = False,
    network: bool = True,
    commit: bool = True,
    window: int = 0,
) -> SyncResult:
    """Pull (rebase), commit, push, best-effort.

    The local commit is always attempted. Network operations only run when an
    ``origin`` remote exists and never fail in a blocking way: problems are
    reported through ``warnings``. A rebase conflict is reported explicitly
    through ``conflict_files``, since it needs a human.

    Parameters
    ----------
    content_dir : pathlib.Path
        Content repo root.
    message : str, optional
        Commit message, defaults to ``sync <host> <timestamp>``.
    push_if_unchanged : bool, optional
        Push even when no new commit was created, to flush commits left behind
        by an earlier offline run.
    network : bool, optional
        When ``False``, skip pull and push entirely.
    commit : bool, optional
        When ``False``, skip the add/commit step (used by :func:`flush`).
    window : int, optional
        Batching window in seconds. While HEAD is an open batch the push is
        held back, since pushing would freeze the commit and forbid amending.

    Returns
    -------
    SyncResult
        A summary of what happened.
    """
    result = SyncResult()
    # `network` first, so a local-only sync skips the `git remote` subprocess.
    origin = network and has_origin(content_dir)
    message = message or _default_message()

    # -- pull ---------------------------------------------------------------
    # Only pull with an upstream configured; otherwise this is the first sync
    # and there is nothing to fetch (the `push -u` below sets it up).
    if origin and has_upstream(content_dir):
        try:
            res = run_git(
                ["pull", "--rebase", "--autostash"],
                cwd=content_dir,
                timeout=NET_TIMEOUT,
            )
            if res.returncode != 0:
                conflicts = run_git(
                    ["diff", "--name-only", "--diff-filter=U"], cwd=content_dir
                ).stdout.split()
                if conflicts:
                    result.conflict_files = conflicts
                    run_git(["rebase", "--abort"], cwd=content_dir)
                    result.warnings.append(
                        "rebase conflict, rebase aborted, resolve by hand"
                    )
                else:
                    result.warnings.append(
                        f"pull failed: {_first_line(res.stderr, 'network')}"
                    )
            else:
                result.pulled = True
        except (subprocess.TimeoutExpired, OSError):
            result.warnings.append("pull failed (timeout / network)")

    # -- commit -------------------------------------------------------------
    if commit:
        result.committed, err = commit_scoped(content_dir, message, window=window)
        if err:
            result.warnings.append(f"commit failed: {err}")

    # -- push ---------------------------------------------------------------
    pending = origin and has_pending(content_dir)
    if (
        origin
        and not result.conflict_files
        and (result.committed or push_if_unchanged or pending)
    ):
        # Pushing an open batch would freeze it, since a pushed commit must
        # never be rewritten. Hold it: the flush after the window sends it.
        if window > 0 and _open_batch(content_dir, window) is not None:
            result.held = True
            return result
        try:
            res = run_git(
                ["push", "-u", "origin", "HEAD"], cwd=content_dir, timeout=NET_TIMEOUT
            )
            if res.returncode == 0:
                result.pushed = True
            else:
                result.warnings.append(
                    "push failed (will retry later): "
                    + _first_line(res.stderr, "network")
                )
        except (subprocess.TimeoutExpired, OSError):
            result.warnings.append("push failed (timeout / network)")

    return result


def _log_flush(content_dir: Path, result: SyncResult) -> None:
    """Record a background sync's problems, which are otherwise invisible."""
    if not (result.warnings or result.conflict_files):
        return
    with open(_state_path(content_dir, "avallon-sync.log"), "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%dT%H:%M:%S}\n")
        for w in result.warnings:
            f.write(f"  warn: {w}\n")
        for c in result.conflict_files:
            f.write(f"  conflict: {c}\n")


def flush(content_dir: Path, *, window: int | None = None) -> None:
    """Run the network half only: pull and push, best-effort, under lock.

    Drains in a loop, because saves may commit *while* this push runs (their
    own flush having found the lock held and given up). We keep pushing as long
    as unpushed commits remain, so the last save of a burst is never stranded.

    Parameters
    ----------
    content_dir : pathlib.Path
        Content repo root.
    window : int, optional
        Batching window in seconds; read from the environment when omitted. A
        held push is not an error: this flush stops, and the next one sends it
        once the window has passed.
    """
    if window is None:
        window = sync_window()
    with sync_lock(content_dir) as acquired:
        if not acquired:
            return  # another sync is running; it drains for us
        for _ in range(10):
            result = sync(
                content_dir, commit=False, push_if_unchanged=True, window=window
            )
            _log_flush(content_dir, result)
            if result.conflict_files or not result.pushed:
                break  # conflict, held batch or network down: retry later
            if unpushed_count(content_dir) == 0:
                break


def spawn_flush(content_dir: Path) -> None:
    """Launch :func:`flush` as a detached process.

    Used by callers that must return immediately (the web editor's save): the
    commit is synchronous and instant, the network is not.
    """
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "flush"],
            env={**os.environ, cc.ENV_VAR: str(content_dir)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        pass  # never blocking: the next sync picks it up


# --------------------------------------------------------------------------- #
# Command line                                                                #
# --------------------------------------------------------------------------- #


def _report(content_dir: Path, result: SyncResult, window: int) -> int:
    """Print a human summary of *result*; return the process exit code."""
    print(f"repo: {content_dir}")
    if result.pulled:
        print("  pulled (rebase)")
    if result.committed:
        print("  committed locally")
    else:
        print("  nothing to commit")
    if result.pushed:
        print("  pushed")
    elif result.held:
        mins = window // 60
        print(f"  push held: the commit is still batchable ({mins} min)")
    elif not has_origin(content_dir):
        print("  no origin: local commit only")
        print(f"    git -C {content_dir} remote add origin <url>")
    for w in result.warnings:
        print(f"  ! {w}")
    if result.conflict_files:
        print("  ! fichiers en conflit :")
        for c in result.conflict_files:
            print(f"      {c}")
        return 1
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command",
        nargs="?",
        default="sync",
        choices=["sync", "flush"],
        help="sync (default) commits then pushes; flush only pushes what is pending",
    )
    parser.add_argument("-m", "--message", help="commit message")
    parser.add_argument("--local", action="store_true", help="commit only, no network")
    parser.add_argument(
        "--no-batch",
        action="store_true",
        help="write a standalone commit instead of folding it into the current batch",
    )
    args = parser.parse_args(argv)

    content_dir = cc.resolve_content_dir()
    if not content_dir.exists():
        sys.exit(f"Notes directory not found: {content_dir}")
    if not is_git_repo(content_dir):
        sys.exit(
            f"{content_dir} is not a git repository.\n"
            "Run `avallon init <path>` to create one."
        )
    # `is_git_repo` is true for any subdirectory of any repo, so a notes
    # directory sitting inside another checkout would pass it. Syncing there
    # would commit notes into that project's history, which is the exact
    # accident this refuses. `avallon init` always produces a repo root.
    if not is_repo_root(content_dir):
        enclosing = run_git(["rev-parse", "--show-toplevel"], cwd=content_dir)
        sys.exit(
            f"{content_dir} is not the root of a git repository: it sits inside\n"
            f"{enclosing.stdout.strip()}.\n"
            "Syncing here would commit the notes into that repository.\n"
            "Run `avallon init <path>` to move the notes out."
        )

    window = 0 if args.no_batch else sync_window()
    if args.command == "flush":
        flush(content_dir, window=window)
        return 0

    result = sync(
        content_dir, message=args.message, network=not args.local, window=window
    )
    return _report(content_dir, result, window)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
