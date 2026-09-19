"""Recent-work signals per board project: Claude sessions and worktree git activity.

A project counts as current when any signal falls inside CURRENT_WINDOW_SECS:
a Claude transcript that names a file inside the project's worktree, a live
Claude session whose cwd is that worktree, a git operation in the worktree
(index/HEAD bookkeeping mtimes), or an edit to the status file itself.
"""

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

CLAUDE_DIR = Path.home() / '.claude'
LIVE_SESSIONS_DIR = CLAUDE_DIR / 'sessions'
TRANSCRIPTS_DIR = CLAUDE_DIR / 'projects'
CURRENT_WINDOW_SECS = 12 * 3600
ACTIVITY_REFRESH_SECS = 15
GIT_ACTIVITY_FILES = ('index', 'HEAD', 'ORIG_HEAD', 'COMMIT_EDITMSG', 'FETCH_HEAD')
TIMESTAMP_RE = re.compile(rb'"timestamp":"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[^"]*"')


def parse_worktree_path(fields):
    """The `worktree:` path, ignoring any trailing note after it."""
    tokens = (fields.get('worktree') or '').split()
    return Path(tokens[0]).expanduser() if tokens else None


def encode_worktree_path_prefixes(path):
    """Byte strings that mean 'a file inside this worktree' in a transcript."""
    needles = {f'{path}/'.encode()}
    if path.is_relative_to(Path.home()):
        needles.add(f'~/{path.relative_to(Path.home())}/'.encode())
    return needles


def mtime_or_none(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def get_latest_timestamp(times):
    return max((t for t in times if t), default=None)


def git_dir_of(worktree):
    dot_git = worktree / '.git'
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text().strip()
        if text.startswith('gitdir:'):
            return Path(text[len('gitdir:'):].strip())
    return None


def read_latest_git_activity_timestamp(worktree):
    """Newest mtime among the worktree's git bookkeeping files, or None."""
    git_dir = git_dir_of(worktree) if worktree else None
    if git_dir is None:
        return None
    return get_latest_timestamp(mtime_or_none(git_dir / name) for name in GIT_ACTIVITY_FILES)


def read_live_session_cwds_with_update_times():
    """(cwd, last-update seconds) for every Claude session with a live marker file."""
    out = []
    for marker in LIVE_SESSIONS_DIR.glob('*.json'):
        try:
            data = json.loads(marker.read_text())
            out.append((Path(data['cwd']), data.get('updatedAt', 0) / 1000))
        except (OSError, ValueError, KeyError):
            continue
    return out


def get_latest_live_session_timestamp_in_worktree(worktree, sessions):
    if worktree is None:
        return None
    return get_latest_timestamp(when for cwd, when in sessions if cwd.is_relative_to(worktree))


def parse_transcript_line_timestamp(line, fallback):
    m = TIMESTAMP_RE.search(line)
    if not m:
        return fallback
    return datetime.fromisoformat(m.group(1).decode() + '+00:00').timestamp()


class WorktreeActivityTranscriptScanner:
    """Finds the newest transcript line naming a file inside each project's worktree.

    Keeps a byte offset per transcript so each pass reads only what was appended;
    a change in the needle set (a project added or its worktree moved) rescans.
    """

    def __init__(self):
        self.offsets = {}
        self.hits = {}
        self.needle_key = None
        self.lock = threading.Lock()

    def scan(self, needles_by_stem, now):
        with self.lock:
            stem_of = {needle: stem for stem, needles in needles_by_stem.items()
                       for needle in needles}
            self.reset_if_needles_changed(stem_of)
            if stem_of:
                pattern = re.compile(b'|'.join(map(re.escape, sorted(stem_of, key=len,
                                                                     reverse=True))))
                for path, mtime in self.recent_transcripts(now):
                    self.scan_file(path, mtime, pattern, stem_of)
            return dict(self.hits)

    def reset_if_needles_changed(self, stem_of):
        key = frozenset(stem_of.items())
        if key != self.needle_key:
            self.needle_key = key
            self.offsets.clear()
            self.hits.clear()

    def recent_transcripts(self, now):
        cutoff = now - CURRENT_WINDOW_SECS
        for path in TRANSCRIPTS_DIR.rglob('*.jsonl'):
            mtime = mtime_or_none(path)
            if mtime and mtime >= cutoff:
                yield path, mtime

    def scan_file(self, path, mtime, pattern, stem_of):
        start = self.offsets.get(path, 0)
        try:
            with path.open('rb') as fh:
                fh.seek(start)
                data = fh.read()
        except OSError:
            return
        # A partial trailing line waits for the next pass so a needle is never split.
        end = data.rfind(b'\n') + 1
        self.offsets[path] = start + end
        for m in pattern.finditer(data, 0, end):
            line_start = data.rfind(b'\n', 0, m.start()) + 1
            line_end = data.find(b'\n', m.end())
            when = parse_transcript_line_timestamp(data[line_start:line_end], mtime)
            stem = stem_of[m.group()]
            self.hits[stem] = max(self.hits.get(stem, 0), when)


SCANNER = WorktreeActivityTranscriptScanner()


def collect_activity_signals_by_project_stem(projects, now):
    """stem -> {signal name: epoch seconds}, keeping only signals inside the window."""
    worktrees = {p['file'].stem: parse_worktree_path(p['fields']) for p in projects}
    needles = {stem: encode_worktree_path_prefixes(wt)
               for stem, wt in worktrees.items() if wt}
    transcript_hits = SCANNER.scan(needles, now)
    sessions = read_live_session_cwds_with_update_times()
    out = {}
    for proj in projects:
        stem = proj['file'].stem
        wt = worktrees[stem]
        live = get_latest_live_session_timestamp_in_worktree(wt, sessions)
        signals = {
            'session': get_latest_timestamp((transcript_hits.get(stem), live)),
            'git': read_latest_git_activity_timestamp(wt),
            'board': mtime_or_none(proj['file']),
        }
        out[stem] = {name: when for name, when in signals.items()
                     if when and now - when <= CURRENT_WINDOW_SECS}
    return out


_cached_signals = None
_refreshed_at = 0.0


def recent_activity_signals_by_project_stem(projects):
    """The cached signals for the index; a stale cache refreshes in the background.

    The first call computes synchronously (a transcript scan can take half a
    second); later calls return the last result and, at most every
    ACTIVITY_REFRESH_SECS, kick off a refresh thread so a page load never waits.
    """
    global _cached_signals, _refreshed_at

    def refresh():
        global _cached_signals
        _cached_signals = collect_activity_signals_by_project_stem(projects, time.time())

    if _cached_signals is None:
        refresh()
        _refreshed_at = time.monotonic()
    elif time.monotonic() - _refreshed_at >= ACTIVITY_REFRESH_SECS:
        _refreshed_at = time.monotonic()
        threading.Thread(target=refresh, daemon=True).start()
    return _cached_signals
