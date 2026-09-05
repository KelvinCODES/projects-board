#!/usr/bin/env python3
"""Live web view of the status files in this directory.

Each *.md file is one project (`_`-prefixed files, like the format template
`_template.md`, are skipped): `- key: value` bullets (phase, branch,
milestone, prs, blockers, last-updated), free paragraphs as description, an
optional `Detail plan: <path>` line, a `## Steps` checkbox list —
`- [x]` done, `- [~]` in progress, `- [ ]` todo, indentation for sub-steps —
an optional `## Lanes` section — `- <name>: #A -> #B -> ~#C (note)` bullets
where `->` chains PRs into a lane, `~#N` marks a parked PR, `!#N` marks a PR
with a human comment awaiting a reply (yellow dotted chip; remove the `!`
once handled), and a trailing parenthetical renders as the lane's note;
chips show live PR state —
an optional `## Log` section — `- <date> <title>: <text>` bullets of session
history, rendered on a separate /log page that the project page links to —
an optional `## Needs action` section — `- #<num>: <context> Recommendation:
<text>` bullets pairing with `!` markers, rendered as a yellow panel beside
"Reviewable now" together with the PR's live human comments —
and any number of `- video: <path>` / `- video-<name>: <path>` bullets that
render as inline players (served with Range support so scrubbing works).
The index lists projects; clicking one shows its step tree. A ↻ refresh
button on the index and project pages re-fetches PR state on demand.
Stdlib only; re-reads the files on every page load, so the files stay the
source of truth.

Usage: board.py [--port 7788] [--no-open] [--archive SLUG]
"""

import argparse
import html
import json
import re
import subprocess
import threading
import time
import webbrowser
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

BOARD_DIR = Path(__file__).resolve().parent
ROW_FIELDS = ('milestone', 'poc-artifacts', 'branch', 'worktree', 'prs', 'blockers')
FIELD_LABELS = {'poc-artifacts': 'Poc Artifacts'}
VIDEO_TYPES = {'.mp4': 'video/mp4', '.mov': 'video/quicktime',
               '.webm': 'video/webm', '.m4v': 'video/x-m4v'}
DEFAULT_REPO = 'moveworks-emu/moveworks'
LINEAR_URL = 'https://linear.app/moveworks/issue/'
PR_URL_RE = re.compile(r'github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)')
PR_NUM_RE = re.compile(r'#(\d+)\b')
PR_JSON_FIELDS = ('title,url,state,isDraft,reviewDecision,statusCheckRollup,'
                  'body,headRefName,baseRefName')
PR_REFRESH_SECS = 120
# How often an index page load may kick an out-of-cycle re-fetch of the `!`
# (needs-you) PRs, so a freshly opened board corrects stale rows quickly
# without letting the 15s auto-rerender hammer gh.
ATTENTION_REFRESH_SECS = 60
TERMINAL_PHASES = frozenset({'done', 'shipped'})
RATE_LIMIT_PAUSE_SECS = 900
pr_cache = {}  # (repo, number) -> {'data': ...} / {'error': ...} / None while fetching
comment_cache = {}  # (repo, number) -> same shape; humans-only PR comments
board_login = None  # the gh account, lazily fetched; own comments aren't "needs action"
PR_CACHE_FILE = BOARD_DIR / '.pr-cache.json'
KNOWN_FIELDS = set(ROW_FIELDS) | {'phase', 'last-updated'}
STEP_STATES = {'x': 'done', ' ': 'todo'}  # anything else (~, -, >, /) = wip

CSS = """
:root {
  color-scheme: light dark;
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --border: rgba(11,11,11,.10); --hairline: #e1e0d9;
  --good: #0ca30c; --good-soft: #63c463; --warn: #fab219; --crit: #d03b3b;
  --shadow: 0 1px 3px rgba(11,11,11,.06);
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #0d0d0d; --surface: #1a1a19;
    --ink: #ffffff; --ink2: #c3c2b7;
    --border: rgba(255,255,255,.10); --hairline: #2c2c2a;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
       font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { padding: 24px 28px 8px; }
header h1 { font-size: 20px; margin: 0 0 2px; }
header .sub { color: var(--muted); font-size: 12px; }
header .sub a { color: var(--ink2); }
main { padding: 8px 28px 32px; }
a { color: inherit; }

/* index */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 16px; max-width: 1200px; margin: 0; justify-content: start; }
a.cardlink { text-decoration: none; display: block; }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px 18px; box-shadow: var(--shadow);
        transition: border-color .12s, transform .12s; height: 100%;
        position: relative; }
a.cardlink:hover .card { border-color: var(--muted); transform: translateY(-1px); }
.cardacts { position: absolute; top: 12px; right: 12px; display: flex; gap: 6px;
            opacity: 0; transition: opacity .12s; }
a.cardlink:hover .cardacts, .cardacts:focus-within { opacity: 1; }
.cardacts .boardbtn { margin-left: 0; }
.docbtn { margin-left: 0; }
.card h3 { font-size: 15px; margin: 0 0 10px; overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.badge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
         color: var(--ink2); border: 1px solid var(--border);
         border-radius: 999px; padding: 1px 9px; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.dot.good { background: var(--good); } .dot.warn { background: var(--warn); }
.dot.crit { background: var(--crit); }
.phase { font-size: 11px; font-weight: 600; text-transform: uppercase;
         letter-spacing: .06em; color: var(--ink2); border: 1px solid var(--hairline);
         border-radius: 4px; padding: 1px 7px; align-self: center; }
.progress { display: flex; align-items: center; gap: 10px; margin: 10px 0 6px; }
.bar { flex: 1; height: 6px; border-radius: 999px; background: var(--hairline);
       overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--good); }
.progress .count { font-size: 12px; color: var(--muted); white-space: nowrap; }
.nowline { font-size: 12.5px; color: var(--ink2); margin: 6px 0 0; }
.nowline .parent, .substep .parent { color: var(--muted); }
.substep { font-size: 12.5px; color: var(--ink2); margin: 2px 0 0 20px; }
.empty { color: var(--muted); }

/* project page */
dl { display: grid; grid-template-columns: max-content 1fr; gap: 3px 12px;
     margin: 0 0 20px; font-size: 13px; max-width: 780px; }
dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }
code, .chip { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.chip { border: 1px solid var(--hairline); border-radius: 4px;
        padding: 0 4px; white-space: nowrap; text-decoration: none; }
a.chip:hover { border-color: var(--muted); }
.chip.pr { display: inline-block; margin: 2px 4px 2px 0; }
.chip.pr::before { content: ''; display: inline-block; width: 7px; height: 7px;
                   border-radius: 50%; margin-right: 4px; background: var(--muted); }
.chip.pr.ok::before, .chip.pr.merged::before { background: var(--good); }
.chip.pr.pending::before { background: var(--warn); }
.chip.pr.fail::before { background: var(--crit); }
.chip.pr.merged { border-color: var(--good); }
.chip.pr.closed { opacity: .55; text-decoration: line-through; }
dd { line-height: 1.7; }
.spinner { display: inline-block; vertical-align: -2px; width: 12px;
           height: 12px; border-radius: 50%; flex: none;
           border: 2px solid var(--hairline); border-top-color: var(--warn);
           animation: spin .9s linear infinite; }
.now { font-size: 10px; font-weight: 600; text-transform: uppercase;
       letter-spacing: .05em; color: var(--ink2);
       border: 1px solid var(--warn); border-radius: 999px; padding: 0 6px; }
@keyframes spin { to { transform: rotate(360deg); } }
.donebar { font-size: 12.5px; color: var(--muted); margin: 16px 2px 0; }
.donebar a { color: var(--ink2); }
.attn { max-width: 1200px; background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; padding: 12px 18px; margin: 4px 0 18px; }
.attn h2 { font-size: 12px; font-weight: 600; text-transform: uppercase;
           letter-spacing: .06em; color: var(--ink2); margin: 0 0 6px; }
.attn ul, .prlist { list-style: none; margin: 0; padding: 0; }
.attn li, .prlist li { display: flex; align-items: baseline; gap: 8px;
                       font-size: 13px; padding: 2px 0; color: var(--ink2); }
.attn .dot, .prlist .dot { align-self: center; }
.prlist { margin: 0 0 20px; max-width: 780px; }

/* lanes */
.laneshead { margin: 14px 0 8px; font-size: 12px; font-weight: 600;
             text-transform: uppercase; letter-spacing: .05em; }
.refreshbtn, .copybtn, .boardbtn { color: var(--ink2); border: 1px solid var(--border);
                                   border-radius: 999px; cursor: pointer;
                                   transition: border-color .12s, color .12s; }
.refreshbtn, .boardbtn { margin-left: 10px; font: 11px system-ui; background: var(--surface);
                         padding: 1px 10px; text-transform: none; letter-spacing: normal; }
.refreshbtn:hover, .boardbtn:hover { border-color: var(--muted); color: var(--ink); }
.refreshbtn:disabled, .boardbtn:disabled { opacity: .6; cursor: default; }
.lanes { margin: 4px 0 20px; display: flex; flex-direction: column; gap: 10px; }
.lane { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.lane .lanename { min-width: 84px; color: var(--ink2); font-size: 12px;
                  text-transform: capitalize; letter-spacing: .04em; flex: none;
                  border-bottom: 1px dashed transparent; cursor: text; outline: none; }
.lane .lanename:hover { border-bottom-color: var(--muted); }
.lane .lanename:focus { color: var(--ink); border-bottom-color: var(--ink2); }
.prchip { display: inline-flex; align-items: center; gap: 6px;
          border: 1px solid var(--border); border-radius: 8px;
          padding: 3px 9px; background: var(--surface); font-size: 12.5px;
          text-decoration: none; box-shadow: var(--shadow); white-space: nowrap; }
.prchip:hover { border-color: var(--muted); }
.prchip.parked { border-style: dashed; opacity: .6; }
.prchip.merged { border-color: var(--good); }
.prchip.reviewable { outline: 2px dotted var(--good-soft); outline-offset: 1px; }
.prchip.approved { outline: 2px solid var(--good); outline-offset: 1px; }
.prchip.blocked { outline: 2px dotted var(--crit); outline-offset: 1px; }
.prchip.attention { outline: 2px dotted var(--warn); outline-offset: 1px; }
.prchip .checks { color: var(--muted); }
.lanes.focus .prchip:not(.need):not(.src) { opacity: .3; }
.lanes .prchip.need { border-color: var(--warn); box-shadow: 0 0 0 1.5px var(--warn);
                      outline: none; opacity: 1; }
.lanes .prchip.src { border-color: var(--ink2); opacity: 1; }
.copybox { max-width: 780px; margin: 0 0 20px; padding: 12px 16px 10px;
           border: 1px solid var(--border); border-left: 3px solid var(--good);
           border-radius: 10px; background: var(--surface); box-shadow: var(--shadow); }
.copyhead { display: flex; align-items: center; gap: 8px; font-size: 12px;
            font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
.copyhead .count { font-weight: 400; color: var(--muted); background: var(--page);
                   border: 1px solid var(--border); border-radius: 999px;
                   padding: 0 8px; font-size: 11.5px; }
.copybtn { margin-left: auto; font: 12px system-ui; background: var(--page);
           padding: 3px 12px; }
.copybtn:hover { border-color: var(--good); color: var(--ink); }
.copybtn.did { border-color: var(--good); color: var(--good); }
.copylist { list-style: none; margin: 8px 0 2px; padding: 0; }
.copylist li { display: flex; align-items: baseline; gap: 8px;
               padding: 3px 0; font-size: 13px; }
.copybox .lanetag { flex: none; align-self: center; color: var(--ink2);
                    background: var(--page); border: 1px solid var(--border);
                    border-radius: 999px; padding: 0 8px; font-size: 11px;
                    text-transform: capitalize; letter-spacing: .04em;
                    min-width: 74px; text-align: center; }
.copybox .prnum { font-weight: 600; text-decoration: none; flex: none; }
.copybox .prnum:hover { text-decoration: underline; }
.copybox .prtitle { color: var(--ink2); overflow-wrap: anywhere; }
.panels { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start;
          max-width: 1200px; margin: 0 0 20px; }
.panels .copybox { flex: 1 1 380px; margin: 0; }
.copybox.action { border-left-color: var(--warn); }
.copybox .cwd { margin: 8px 0 0; font: 12px ui-monospace, monospace; color: var(--muted); }
.copybox .nvimcmd { font: 12px ui-monospace, monospace; overflow-wrap: anywhere; }
.copylist li.lit { background: var(--good-soft); border-radius: 6px;
                   margin: 0 -6px; padding-left: 6px; padding-right: 6px; }
.arow { display: flex; align-items: baseline; gap: 8px; padding: 10px 0 2px;
        font-size: 13px; }
.action .cmt { margin: 2px 0; font-size: 12.5px; color: var(--ink2); }
.action .cmt .who { font-weight: 600; }
.action .ctx { margin: 4px 0 6px; font-size: 12.5px; }
.lane .arrow { color: var(--muted); flex: none; }
.lane .lanenote { color: var(--muted); font-size: 11.5px; }

/* metro view */
.metro { padding: 6px 0 8px; max-width: 720px; }
.station { position: relative; padding: 0 0 26px 42px; }
.station::before { content: ''; position: absolute; left: 11px; top: 8px; bottom: -8px;
                   width: 4px; border-radius: 2px; background: var(--hairline); }
.station.done::before { background: var(--good); }
.station:last-child::before { display: none; }
.station:last-child { padding-bottom: 0; }
.mdot { position: absolute; left: 0; top: 0; width: 26px; height: 26px;
        border-radius: 50%; display: flex; align-items: center;
        justify-content: center; font-size: 13px; background: var(--surface); }
.mdot.done { background: var(--good); color: #fff; }
.mdot.todo { border: 3px solid var(--hairline); }
.mdot.wip { border: 3px solid var(--warn);
            background: color-mix(in srgb, var(--warn) 12%, var(--surface)); }
.mlabel { font-size: 13.5px; padding-top: 3px; }
.station.todo > .mlabel { color: var(--muted); }
.mbranch { list-style: none; margin: 6px 0 0 5px; padding: 0 0 0 16px;
           border-left: 2px solid var(--hairline); font-size: 12.5px;
           color: var(--ink2); }
.mbranch li { padding: 2px 0; }
.mbranch li.todo { color: var(--muted); }
.mbranch .glyph { color: var(--good); }
.mbranch li.todo .glyph { color: var(--muted); }

.clips { display: flex; flex-wrap: wrap; gap: 16px; margin: 4px 0 20px; }
.clip { margin: 0; }
.clip video { width: 480px; max-width: 100%; display: block; background: #000;
              border: 1px solid var(--border); border-radius: 8px; }
.clip figcaption { font-size: 12px; color: var(--muted); margin-top: 4px; }
.desc { max-width: 780px; }
.desc p { color: var(--ink2); font-size: 13px; }
.desc .deschead { font-size: 12px; font-weight: 600; text-transform: uppercase;
                  letter-spacing: .05em; color: var(--ink2); margin: 14px 0 4px; }
.desc .descli { margin: 3px 0 3px 14px; }
.log { max-width: 780px; }
.log h3 { font-size: 13px; margin: 18px 0 4px; }
.log p { color: var(--ink2); font-size: 13px; margin: 0; }
pre { background: var(--surface); border: 1px solid var(--border);
      border-radius: 8px; padding: 16px; overflow-x: auto;
      white-space: pre-wrap; font-size: 13px; }
"""

# Re-render in place, but only while the tab is visible; a hidden tab does no
# work and catches up the moment it is shown again. Only touch the DOM when
# the files changed, so scroll position survives.
JS = """
async function refresh() {
  try {
    const text = await (await fetch(location.href)).text();
    const fresh = new DOMParser().parseFromString(text, 'text/html');
    if (document.activeElement && document.activeElement.closest('.lanename')) return;
    // The stylesheet lives outside <main>, so an edit to CSS would never reach
    // a long-open tab without this.
    const css = document.querySelector('style'), freshCss = fresh.querySelector('style');
    if (css && freshCss && css.textContent !== freshCss.textContent)
      css.textContent = freshCss.textContent;
    const cur = document.querySelector('main'), nxt = fresh.querySelector('main');
    if (cur && nxt && cur.innerHTML !== nxt.innerHTML) cur.innerHTML = nxt.innerHTML;
  } catch (e) {}
}
function postJSON(path, body) {
  return fetch(path, {method: 'POST',
                      headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify(body)});
}
setInterval(() => { if (!document.hidden) refresh(); }, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
document.addEventListener('click', (e) => {
  if (!(e.target instanceof Element)) return;
  const btn = e.target.closest('.copybtn');
  if (!btn) return;
  const pre = btn.closest('.copybox').querySelector('.copytext');
  // Real selection + execCommand: ad blockers (uBlock ClickFix guard) reject
  // scripted clipboard writes but allow copying visibly selected text.
  pre.hidden = false;
  const sel = getSelection(), range = document.createRange();
  sel.removeAllRanges();
  range.selectNodeContents(pre);
  sel.addRange(range);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (err) {}
  if (ok) {
    sel.removeAllRanges();
    pre.hidden = true;
    btn.classList.add('did');
    btn.textContent = '✓ copied';
    setTimeout(() => { btn.classList.remove('did'); btn.textContent = '⧉ copy list'; }, 1500);
  } else {
    btn.textContent = 'press ⌘C';  // text stays visible and selected
    setTimeout(() => { btn.textContent = '⧉ copy list'; pre.hidden = true; }, 4000);
  }
});
document.addEventListener('click', async (e) => {
  if (!(e.target instanceof Element)) return;
  const btn = e.target.closest('.refreshbtn');
  if (!btn || btn.disabled) return;
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '↻ refreshing…';
  let ok = false;
  try { ok = (await postJSON('/refresh', {p: btn.dataset.stem})).ok; } catch (err) {}
  if (ok) await refresh();
  // refresh() may have replaced this button with a fresh one; if not
  // (identical HTML), restore it in place.
  btn.disabled = false;
  btn.textContent = ok ? label : '✕ failed';
  if (!ok) setTimeout(() => { btn.textContent = label; }, 2500);
});
document.addEventListener('click', (e) => {
  if (!(e.target instanceof Element)) return;
  const btn = e.target.closest('.docbtn');
  if (!btn) return;
  e.preventDefault();
  window.open(btn.dataset.url, '_blank', 'noopener');
});
document.addEventListener('click', async (e) => {
  if (!(e.target instanceof Element)) return;
  const btn = e.target.closest('.boardbtn');
  if (!btn || btn.disabled || btn.classList.contains('docbtn')) return;
  e.preventDefault();  // index cards nest these buttons inside the card link
  const label = btn.textContent;
  btn.disabled = true;
  let ok = false;
  try { ok = (await postJSON(btn.dataset.action, {p: btn.dataset.stem})).ok; } catch (err) {}
  // Reload rather than patch: the header (outside <main>) holds these
  // buttons, and both the badge row and the button set change state.
  if (ok) { location.reload(); return; }
  btn.disabled = false;
  btn.textContent = '✕ failed';
  setTimeout(() => { btn.textContent = label; }, 2500);
});
document.addEventListener('keydown', (e) => {
  const el = e.target instanceof Element && e.target.closest('.lanename');
  if (!el) return;
  if (e.key === 'Enter') { e.preventDefault(); el.blur(); }
  if (e.key === 'Escape') { el.textContent = el.dataset.name; el.blur(); }
});
document.addEventListener('focusout', async (e) => {
  const el = e.target instanceof Element && e.target.closest('.lanename');
  if (!el) return;
  const next = el.textContent.trim(), prev = el.dataset.name;
  if (!next || next === prev) { el.textContent = prev; return; }
  try {
    const res = await postJSON('/lane-rename', {p: el.dataset.stem, old: prev, new: next});
    if (!res.ok) throw new Error();
    el.dataset.name = next;
  } catch (err) { el.textContent = prev; }
});
// Hovering a PR link in a panel (nvim diffs, reviewable) lights its chip in the lanes.
function lanesFor(el) { return el.closest('.lanes') || document.querySelector('.lanes'); }
document.addEventListener('mouseover', (e) => {
  if (!(e.target instanceof Element)) return;
  const link = e.target.closest('.copybox .prnum[data-pr]');
  if (link) {
    const lanes = lanesFor(link);
    if (!lanes) return;
    lanes.classList.add('focus');
    lanes.querySelectorAll(`.prchip[data-pr="${link.dataset.pr}"]`)
         .forEach((c) => c.classList.add('src'));
    return;
  }
  const chip = e.target.closest('.prchip'), lanes = e.target.closest('.lanes');
  if (!chip || !lanes) return;
  document.querySelectorAll(`.copybox .prnum[data-pr="${chip.dataset.pr}"]`)
          .forEach((a) => a.closest('li').classList.add('lit'));
  const needs = (chip.dataset.needs || '').split(' ').filter(Boolean);
  if (!needs.length) return;
  lanes.classList.add('focus');
  chip.classList.add('src');
  for (const n of needs)
    lanes.querySelectorAll(`.prchip[data-pr="${n}"]`).forEach((c) => c.classList.add('need'));
});
document.addEventListener('mouseout', (e) => {
  if (!(e.target instanceof Element)) return;
  const lanes = e.target.closest('.lanes') ||
                (e.target.closest('.copybox .prnum[data-pr]') && lanesFor(e.target));
  if (!lanes) return;
  lanes.classList.remove('focus');
  lanes.querySelectorAll('.need, .src').forEach((c) => c.classList.remove('need', 'src'));
  document.querySelectorAll('.copylist li.lit').forEach((li) => li.classList.remove('lit'));
});
"""


def status_files(board_dir, archived=False):
    base = board_dir / 'archive' if archived else board_dir
    return sorted(base.glob('[!_]*.md'))


def find_status(board_dir, stem):
    for base in (board_dir, board_dir / 'archive'):
        path = (base / f'{stem}.md').resolve()
        if (path.is_file() and not path.name.startswith('_')
                and path.is_relative_to(board_dir)):
            return path
    return None


def move_project(board_dir, stem, unarchive=False):
    """Move a status file into archive/ (or back out with unarchive). True on success."""
    if '/' in stem or '\\' in stem:
        return False
    src_base, dst_base = ((board_dir / 'archive', board_dir) if unarchive
                          else (board_dir, board_dir / 'archive'))
    src = (src_base / f'{stem}.md').resolve()
    if not (src.is_file() and not src.name.startswith('_')
            and src.is_relative_to(board_dir)):
        return False
    dst_base.mkdir(exist_ok=True)
    dst = dst_base / src.name
    if dst.exists():
        return False
    src.rename(dst)
    return True


def parse_status_file(path):
    proj = {'file': path, 'title': path.stem, 'fields': {}, 'desc': [],
            'plan': None, 'steps': [], 'lanes': [], 'log': [], 'actions': {},
            'nvim': [], 'nvim_cwd': ''}
    key, para, stack, section, last_action = None, [], [], None, None

    def flush_para():
        if para:
            proj['desc'].append(' '.join(para))
            para.clear()

    for line in path.read_text().splitlines():
        # A checkbox may be indented, so it must win over field continuation.
        if m := re.match(r'(\s*)-\s+\[(.)\]\s+(.*)', line):
            key = None
            flush_para()
            node = {'label': m.group(3).strip(), 'children': [],
                    'state': STEP_STATES.get(m.group(2).lower(), 'wip')}
            indent = len(m.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            (stack[-1][1]['children'] if stack else proj['steps']).append(node)
            stack.append((indent, node))
            continue
        if line[:1].isspace() and line.strip():
            if key:
                proj['fields'][key] += ' ' + line.strip()
                continue
            if section == 'log' and proj['log']:
                k, v = proj['log'][-1]
                proj['log'][-1] = (k, v + ' ' + line.strip())
                continue
            if section == 'needs action' and last_action:
                proj['actions'][last_action] += ' ' + line.strip()
                continue
            if stack:  # wrapped continuation of the last checkbox step
                stack[-1][1]['label'] += ' ' + line.strip()
                continue
        key = None
        if section == 'needs action' and (m := re.match(r'-\s+#?(\d+):\s*(.*)', line)):
            flush_para()
            last_action = int(m.group(1))
            proj['actions'][last_action] = m.group(2).strip()
            continue
        if section == 'nvim':
            if m := re.match(r'-\s+cwd:\s*(.*)', line):
                proj['nvim_cwd'] = m.group(1).strip()
                continue
            if m := re.match(r'-\s+#?(\d+):\s*(.*)', line):
                proj['nvim'].append((int(m.group(1)), m.group(2).strip()))
                continue
        # Log headings are free text ("2026-08-31 lane restructure"), so the
        # key may contain spaces there, unlike field bullets.
        if section == 'log' and (m := re.match(r'-\s+([^:]+):\s*(.*)', line)):
            flush_para()
            proj['log'].append((m.group(1).strip(), m.group(2).strip()))
            continue
        # The colon needs trailing space or EOL: `- prs: #322` is a field,
        # `- 1:1 DM stays flat` is prose.
        if m := re.match(r'-\s+([\w-]+):(?:\s+(.*)|\s*$)', line):
            flush_para()
            if section == 'lanes':
                proj['lanes'].append((m.group(1), (m.group(2) or '').strip()))
                continue
            key = m.group(1)
            proj['fields'][key] = (m.group(2) or '').strip()
        elif m := re.match(r'detail plan:\s*(.*)', line, re.IGNORECASE):
            flush_para()
            proj['plan'] = m.group(1).strip()
        elif line.startswith('## '):
            flush_para()
            section = line[3:].strip().lower()
        elif line.startswith('# '):
            flush_para()
            proj['title'] = line[2:].strip()
        elif line.strip() and not line.startswith('#'):
            # A plain (non-field) bullet stands alone as its own desc line
            # instead of joining the paragraph flow.
            if line.startswith('- '):
                flush_para()
                proj['desc'].append('• ' + line[2:].strip())
            else:
                para.append(line.strip())
        else:  # blank line or section heading
            flush_para()
    flush_para()
    proj['phase_label'] = phase_of(proj['fields'].get('phase'))
    proj['staleness'] = staleness_of(proj['fields'], path)
    return proj


def phase_of(value):
    m = re.match(r'[\w-]+', value or '')
    return m.group().lower() if m else 'unknown'


def is_set(value):
    """A missing field and a 'none'/'none yet' sentinel both count as unset."""
    return bool(value) and not value.lower().startswith('none')


def is_video(key, value):
    return key.split('-')[0] == 'video' and Path(value).suffix.lower() in VIDEO_TYPES


def staleness_of(fields, path):
    m = re.search(r'\d{4}-\d{2}-\d{2}', fields.get('last-updated', ''))
    if m:
        updated = date.fromisoformat(m.group())
    else:
        updated = date.fromtimestamp(path.stat().st_mtime)
    days = (date.today() - updated).days
    if days <= 0:
        return 0, 'good', 'updated today'
    kind = 'good' if days <= 2 else 'warn' if days <= 7 else 'crit'
    return days, kind, f'updated {days}d ago'


def sort_key(proj):
    """Blocked projects first, then freshest first."""
    return (not is_set(proj['fields'].get('blockers')), proj['staleness'][0])


def leaves(nodes, trail=()):
    """Yield (ancestor_trail, leaf) pairs, depth-first."""
    for n in nodes:
        if n['children']:
            yield from leaves(n['children'], trail + (n,))
        else:
            yield trail, n


def current_step(ls):
    return (next((pair for pair in ls if pair[1]['state'] == 'wip'), None)
            or next((pair for pair in ls if pair[1]['state'] == 'todo'), None))


def decorate(text, links=True):
    """Escape, then style ticket IDs and commit hashes and linkify URLs.

    links=False keeps everything linkless — required for text that renders
    inside another <a> (the index card), where a nested anchor would make
    the HTML parser fracture the outer link.
    """
    ticket = (rf'<a class="chip" href="{LINEAR_URL}\1">\1</a>' if links
              else r'<span class="chip">\1</span>')
    out = []
    for i, part in enumerate(re.split(r'(https?://\S+)', text)):
        esc = html.escape(part)
        if i % 2:
            out.append(f'<a href="{esc}">{esc}</a>' if links else esc)
        else:
            esc = re.sub(r'\[?\b([A-Z][A-Z0-9]+-\d+)\b\]?', ticket, esc)
            esc = re.sub(r'\b((?=\w*\d)[0-9a-f]{7,40})\b', r'<code>\1</code>', esc)
            out.append(esc)
    return ''.join(out)


def badge(kind, glyph, label, tooltip=''):
    tip = f' title="{html.escape(tooltip, quote=True)}"' if tooltip else ''
    return (f'<span class="badge"{tip}><span class="dot {kind}"></span>'
            f'{glyph} {html.escape(label)}</span>')


def badges_for(proj):
    _, kind, label = proj['staleness']
    blockers = proj['fields'].get('blockers', '')
    out = [f'<span class="phase">{html.escape(proj["phase_label"])}</span>',
           badge(kind, '✓' if kind == 'good' else '!', label)]
    if is_set(blockers):
        out.append(badge('crit', '✕', 'blocked', blockers))
    return ''.join(out)


def poc_doc_url(fields):
    """The go/no-go Notion URL from the `- poc-artifacts:` bullet, or ''."""
    value = fields.get('poc-artifacts') or fields.get('poc-doc', '')
    m = re.search(r'https?://\S+', value)
    return m.group() if m else ''


def poc_doc_button(fields):
    url = poc_doc_url(fields)
    if not url:
        return ''
    # A button, not an <a>: index cards live inside the card link, and a
    # nested anchor would split it.
    return (f'<button class="boardbtn docbtn" type="button" '
            f'data-url="{html.escape(url)}" '
            f'title="open the POC go/no-go page">📄 go/no-go</button>')


def render_index_card(proj):
    ls = list(leaves(proj['steps']))
    done = sum(leaf['state'] == 'done' for _, leaf in ls)
    parts = [f'<h3>{html.escape(proj["title"])}</h3>',
             f'<div class="badges">{badges_for(proj)}'
             f'{poc_doc_button(proj["fields"])}</div>']
    if ls:
        pct = round(100 * done / len(ls))
        parts.append(f'<div class="progress"><span class="bar">'
                     f'<i style="width:{pct}%"></i></span>'
                     f'<span class="count">{done}/{len(ls)} steps</span></div>')
    now = current_step(ls)
    if now:
        trail, leaf = now
        leaf_html = decorate(leaf['label'], links=False)
        if trail:
            parts.append(f'<p class="nowline"><span class="spinner"></span> '
                         f'{decorate(trail[0]["label"], links=False)}</p>')
            parts.append(f'<p class="substep"><span class="parent">↳</span> {leaf_html}</p>')
        else:
            parts.append(f'<p class="nowline"><span class="spinner"></span> {leaf_html}</p>')
    href = project_href(proj['file'].stem)
    acts = f'<div class="cardacts">{project_buttons(proj["file"], proj)}</div>'
    return f'<a class="cardlink" href="{href}"><article class="card">' \
           f'{"".join(parts)}{acts}</article></a>'


def render_index(board_dir):
    refresh_attention_async(board_dir)
    projects = sorted((parse_status_file(p) for p in status_files(board_dir)),
                      key=sort_key)
    active = [p for p in projects if p['phase_label'] not in TERMINAL_PHASES]
    done = [p for p in projects if p['phase_label'] in TERMINAL_PHASES]
    if active:
        body = (render_attention(active) + '<div class="grid">'
                + ''.join(render_index_card(p) for p in active) + '</div>')
    else:
        body = f'<p class="empty">No active projects in {html.escape(str(board_dir))}</p>'

    groups = []
    if done:
        groups.append(f'<a href="/shipped">shipped ({len(done)})</a>')
    archived_count = len(status_files(board_dir, archived=True))
    if archived_count:
        groups.append(f'<a href="/archived">archived ({archived_count})</a>')
    if groups:
        body += f'<p class="donebar">{" · ".join(groups)}</p>'
    sub = (f'{len(projects)} project(s) · {html.escape(str(board_dir))}'
           f' · rendered {datetime.now().strftime("%H:%M:%S")}'
           f' · {refresh_button("")}')
    return page('Projects board', sub, body, script=JS)


def render_group(board_dir, archived=False):
    """The shipped or archived projects as a card grid of their own."""
    if archived:
        projects = [parse_status_file(f) for f in status_files(board_dir, archived=True)]
        title = 'Archived projects'
    else:
        projects = [p for p in (parse_status_file(f) for f in status_files(board_dir))
                    if p['phase_label'] in TERMINAL_PHASES]
        title = 'Shipped projects'
    projects.sort(key=sort_key)
    body = ('<div class="grid">' + ''.join(render_index_card(p) for p in projects)
            + '</div>' if projects else '<p class="empty">Nothing here yet</p>')
    sub = f'<a href="/">← projects</a> · {len(projects)} project(s)'
    return page(title, sub, body, script=JS)


def glyph_html(state):
    if state == 'wip':
        return '<span class="glyph spinner"></span>'
    return f'<span class="glyph">{"✓" if state == "done" else "○"}</span>'


def render_view_metro(proj):
    def branch(nodes):
        if not nodes:
            return ''
        items = []
        for n in nodes:
            items.append(f'<li class="{n["state"]}">{glyph_html(n["state"])} '
                         f'{decorate(n["label"])}{branch(n["children"])}</li>')
        return f'<ul class="mbranch">{"".join(items)}</ul>'

    stations = []
    for n in proj['steps']:
        if n['state'] == 'wip':
            dot = '<span class="mdot wip"><span class="spinner"></span></span>'
            now = ' <span class="now">now</span>'
        else:
            dot = (f'<span class="mdot {n["state"]}">'
                   f'{"✓" if n["state"] == "done" else ""}</span>')
            now = ''
        stations.append(f'<div class="station {n["state"]}">{dot}'
                        f'<div class="mlabel">{decorate(n["label"])}{now}'
                        f'{branch(n["children"])}</div></div>')
    return f'<div class="metro">{"".join(stations)}</div>'


def pr_refs(fields):
    val = fields.get('prs', '')
    if not is_set(val):
        return []
    refs = [(m.group(1), int(m.group(2))) for m in PR_URL_RE.finditer(val)]
    seen = {num for _, num in refs}
    refs += [(DEFAULT_REPO, int(m.group(1))) for m in PR_NUM_RE.finditer(val)
             if int(m.group(1)) not in seen]
    return refs


def fetch_pr(repo, num):
    try:
        out = subprocess.run(
            ['gh', 'pr', 'view', str(num), '--repo', repo,
             '--json', PR_JSON_FIELDS],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {'error': str(e)}
    if out.returncode:
        return {'error': out.stderr.strip() or f'gh exited {out.returncode}'}
    try:
        return {'data': json.loads(out.stdout)}
    except ValueError as e:
        return {'error': str(e)}


def is_settled(ref):
    """A merged or closed PR never changes; fetch it once and keep it."""
    entry = pr_cache.get(ref)
    return bool(entry) and entry.get('data', {}).get('state') in ('MERGED', 'CLOSED')


def is_rate_limited(entry):
    return 'rate limit' in (entry or {}).get('error', '').lower()


def fetch_board_login():
    global board_login
    out = subprocess.run(['gh', 'api', 'user', '-q', '.login'],
                         capture_output=True, text=True, timeout=30)
    if not out.returncode:
        board_login = out.stdout.strip()


def is_human_comment(c):
    user = c.get('user') or {}
    login = user.get('login', '')
    return (user.get('type') != 'Bot' and not login.endswith('[bot]')
            and login != board_login)


def fetch_pr_comments(repo, num):
    """Review + issue comments on a PR from humans other than the board user."""
    raw = []
    for kind in ('pulls', 'issues'):
        try:
            out = subprocess.run(
                ['gh', 'api', f'repos/{repo}/{kind}/{num}/comments'],
                capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {'error': str(e)}
        if out.returncode:
            return {'error': out.stderr.strip() or f'gh exited {out.returncode}'}
        try:
            raw += json.loads(out.stdout)
        except ValueError as e:
            return {'error': str(e)}
    humans = [c for c in sorted(raw, key=lambda c: c.get('created_at', ''))
              if is_human_comment(c)]
    return {'data': [{'author': c['user']['login'], 'body': c.get('body', ''),
                      'path': c.get('path', ''), 'url': c.get('html_url', ''),
                      'created': c.get('created_at', '')[:10]} for c in humans]}


def request_comments(repo, num):
    if (repo, num) not in comment_cache:
        comment_cache[(repo, num)] = None
        threading.Thread(
            target=lambda: comment_cache.update(
                {(repo, num): fetch_pr_comments(repo, num)}),
            daemon=True).start()


def load_pr_cache():
    """Warm-start from the last saved states so a restart never shows less
    than the previous process knew."""
    try:
        saved = json.loads(PR_CACHE_FILE.read_text())
    except (OSError, ValueError):
        return
    for key, data in saved.items():
        repo, _, num = key.rpartition('#')
        pr_cache[(repo, int(num))] = {'data': data}


def save_pr_cache():
    good = {f'{repo}#{num}': entry['data']
            for (repo, num), entry in dict(pr_cache).items()
            if entry and 'data' in entry}
    tmp = PR_CACHE_FILE.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(good))
        tmp.replace(PR_CACHE_FILE)
    except OSError:
        pass


def project_prs(parsed):
    """All PR refs a project mentions, plus the subset marked `!` (attention)."""
    refs, attention = set(pr_refs(parsed['fields'])), set()
    for _name, node in lane_nodes(parsed['lanes']):
        refs.add((DEFAULT_REPO, node.num))
        if node.attention:
            attention.add((DEFAULT_REPO, node.num))
    return refs, attention


def board_prs(board_dir):
    refs, attention = set(), set()
    for f in status_files(board_dir):
        try:
            r, a = project_prs(parse_status_file(f))
        except OSError:
            continue
        refs |= r
        attention |= a
    return refs, attention


def fetch_prs(refs, attention):
    """One fetch pass over the caches. Returns True if gh was rate limited."""
    todo = [ref for ref in refs if not is_settled(ref)]
    rate_limited, stored = False, False

    def keep_or_store(cache, ref, entry):
        nonlocal rate_limited, stored
        if 'error' in entry:
            rate_limited = rate_limited or is_rate_limited(entry)
            if 'data' in (cache.get(ref) or {}):
                return  # stale state beats "unavailable" during an outage
        cache[ref] = entry
        stored = stored or cache is pr_cache

    with ThreadPoolExecutor(max_workers=4) as pool:
        for ref, entry in zip(todo, pool.map(lambda r: fetch_pr(*r), todo)):
            keep_or_store(pr_cache, ref, entry)
        if not rate_limited:
            todo = sorted(ref for ref in attention if not is_settled(ref))
            for ref, entry in zip(todo, pool.map(lambda r: fetch_pr_comments(*r),
                                                 todo)):
                keep_or_store(comment_cache, ref, entry)
    if stored:
        save_pr_cache()
    return rate_limited


def refresh_now(board_dir, stem=''):
    """Synchronous fetch for the /refresh endpoint; one project or the whole
    board. False when the stem is unknown or gh is rate limited."""
    if stem:
        path = find_status(board_dir, stem)
        if path is None:
            return False
        refs, attention = project_prs(parse_status_file(path))
    else:
        refs, attention = board_prs(board_dir)
    return not fetch_prs(refs, attention)


def poll_prs(board_dir):
    fetch_board_login()
    while True:
        rate_limited = fetch_prs(*board_prs(board_dir))
        time.sleep(RATE_LIMIT_PAUSE_SECS if rate_limited else PR_REFRESH_SECS)


_attention_refreshed_at = 0.0


def refresh_attention_async(board_dir):
    """Re-fetch the needs-you PRs in the background on an index page load.

    The 15s auto-rerender then picks up the corrected state, so a stale
    `!` row (e.g. a PR closed since the last poll) clears within one cycle
    instead of waiting out PR_REFRESH_SECS. Throttled; rendering never blocks.
    """
    global _attention_refreshed_at
    now = time.monotonic()
    if now - _attention_refreshed_at < ATTENTION_REFRESH_SECS:
        return
    _attention_refreshed_at = now

    def work():
        attention = board_prs(board_dir)[1]
        if attention:
            fetch_prs(attention, attention)

    threading.Thread(target=work, daemon=True).start()


def request_pr(repo, num):
    """Fetch a PR outside the poll set (e.g. archived) in the background."""
    if (repo, num) not in pr_cache:
        pr_cache[(repo, num)] = None
        threading.Thread(
            target=lambda: pr_cache.update({(repo, num): fetch_pr(repo, num)}),
            daemon=True).start()


def pr_summary(repo, num):
    entry = pr_cache.get((repo, num))
    if entry is None or 'error' in entry:
        return entry
    d = entry['data']
    ok = fail = pending = 0
    for c in d.get('statusCheckRollup') or []:
        # Jenkins StatusContext carries `state`; a CheckRun carries `conclusion`.
        concl = (c.get('conclusion') or c.get('state') or '').upper()
        if concl in ('SUCCESS', 'NEUTRAL', 'SKIPPED'):
            ok += 1
        elif concl in ('FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT',
                       'ACTION_REQUIRED', 'STALE'):
            fail += 1
        else:
            pending += 1
    needs = []
    if m := re.search(r'DEPENDS_ON_PR_MERGE[^\n]*', d.get('body') or ''):
        needs = [int(n) for n in PR_NUM_RE.findall(m.group(0))]
    return {'needs': needs,
            'title': d.get('title', ''), 'url': d.get('url', ''),
            'branch': d.get('headRefName', ''), 'base': d.get('baseRefName', ''),
            'draft': d.get('isDraft', False), 'merged': d.get('state') == 'MERGED',
            'closed': d.get('state') == 'CLOSED',
            'review': (d.get('reviewDecision') or '').lower().replace('_', ' '),
            'ok': ok, 'fail': fail, 'pending': pending,
            'ready': (d.get('state') == 'OPEN' and not d.get('isDraft')
                      and ok > 0 and fail == 0 and pending == 0)}


LANE_NODE_RE = re.compile(r'([~!]*)#(\d+)$')
LaneNode = namedtuple('LaneNode', 'num parked attention')
ATTENTION_NOTE = 'human comment, needs you'


def parse_lane(value):
    """`#A -> ~#B -> !#C (note)` -> ([LaneNode, ...], note)."""
    note = ''
    if m := re.search(r'\(([^)]*)\)\s*$', value):
        note, value = m.group(1), value[:m.start()]
    nodes = [LaneNode(int(m.group(2)), '~' in m.group(1), '!' in m.group(1))
             for part in value.split('->')
             if (m := LANE_NODE_RE.match(part.strip()))]
    return nodes, note


def lane_nodes(lanes):
    for name, value in lanes:
        for node in parse_lane(value)[0]:
            yield name, node


def pr_url(num):
    return f'https://github.com/{DEFAULT_REPO}/pull/{num}'


def is_merged(smry):
    return bool(smry and smry.get('merged'))


def is_closed_or_merged(smry):
    return bool(smry and (smry.get('merged') or smry.get('closed')))


def deps_merged(needs):
    for n in needs:
        request_pr(DEFAULT_REPO, n)  # a dep outside every lane is otherwise never fetched
    return all((dep := pr_summary(DEFAULT_REPO, n)) and dep.get('merged')
               for n in needs)


def is_approved(smry):
    return smry['review'] == 'approved'


def chip_state_class(smry, parked):
    """Outline for an open PR; the caller's `parked`/`attention` outrank these."""
    if parked:
        return ''
    if is_approved(smry):
        return ' approved'
    return ' reviewable' if deps_merged(smry['needs']) else ' blocked'


def refresh_button(stem):
    """`stem` scopes the re-fetch to one project; '' means the whole board."""
    return (f'<button class="refreshbtn" type="button" '
            f'data-stem="{html.escape(stem)}" '
            f'title="re-fetch PR state now">↻ refresh</button>')


def render_lanes(lanes, stem=''):
    rows = []
    for name, value in lanes:
        nodes, note = parse_lane(value)
        chips = []
        for num, parked, attention in nodes:
            request_pr(DEFAULT_REPO, num)
            smry = pr_summary(DEFAULT_REPO, num)
            cls, dot, extra, title = 'prchip', 'warn', 'loading…', ''
            url = pr_url(num)
            needs = []
            if smry and 'error' not in smry:
                title, url, needs = smry['title'], smry['url'], smry['needs']
                if smry['branch']:
                    title += f' · {smry["branch"]} → {smry["base"]}'
                if needs:
                    title += ' · needs ' + ', '.join(f'#{n}' for n in needs)
                if smry['merged']:
                    cls, dot, extra = cls + ' merged', 'good', 'merged'
                else:
                    dot = ('crit' if smry['fail'] else
                           'warn' if smry['pending'] else 'good')
                    extra = f'{smry["ok"]}✓'
                    detail = [f'{smry["ok"]} checks passed']
                    if smry['fail']:
                        extra += f' {smry["fail"]}✗'
                        detail.append(f'{smry["fail"]} failing')
                    if smry['pending']:
                        extra += f' {smry["pending"]} running'
                        detail.append(f'{smry["pending"]} still running')
                    if smry['draft']:
                        extra += ' · draft'
                    if is_approved(smry):
                        extra += ' · approved'
                        detail.append('approved')
                    title += ' · ' + ', '.join(detail)
                    if not attention:
                        cls += chip_state_class(smry, parked)
            elif smry and 'error' in smry:
                extra = 'state unavailable'
            # A stale `~` or `!` left on a merged PR must not restyle it.
            if parked and not is_merged(smry):
                cls += ' parked'
                extra = 'parked'
            if attention and not is_merged(smry):
                cls += ' attention'
                extra += ' · needs you'
                title = f'{title} · {ATTENTION_NOTE}' if title else ATTENTION_NOTE
            needs_attr = ' '.join(str(n) for n in needs)
            chips.append(
                f'<a class="{cls}" href="{html.escape(url)}" data-pr="{num}" '
                f'data-needs="{needs_attr}" title="{html.escape(title)}">'
                f'<span class="dot {dot}"></span>'
                f'#{num}<span class="checks">{html.escape(extra)}</span></a>')
        row = (f'<div class="lane"><span class="lanename" contenteditable="plaintext-only" '
               f'spellcheck="false" data-stem="{html.escape(stem)}" '
               f'data-name="{html.escape(name)}" title="click to rename">'
               f'{html.escape(name)}</span>'
               + '<span class="arrow">→</span>'.join(chips))
        if note:
            row += f'<span class="lanenote">{html.escape(note)}</span>'
        rows.append(row + '</div>')
    return (f'<div class="laneshead">PR lanes{refresh_button(stem)}</div>'
            f'<div class="lanes">{"".join(rows)}</div>')


def render_reviewable(lanes):
    items = []
    for name, node in lane_nodes(lanes):
        if node.parked:
            continue
        smry = pr_summary(DEFAULT_REPO, node.num)
        if not smry or 'error' in smry or smry['merged']:
            continue
        if not is_approved(smry) and deps_merged(smry['needs']):
            items.append((name, node.num, smry['title'], smry['url']))
    if not items:
        return ''
    rows = ''.join(
        f'<li><span class="lanetag">{html.escape(lane)}</span>'
        f'<a class="prnum" href="{html.escape(url)}" data-pr="{num}">#{num}</a>'
        f'<span class="prtitle">{html.escape(title)}</span></li>'
        for lane, num, title, url in items)
    text = html.escape('\n'.join(
        f'- {lane}: [#{num} {title}]({url})' for lane, num, title, url in items))
    return (f'<div class="copybox"><div class="copyhead">Reviewable now'
            f'<span class="count">{len(items)}</span>'
            f'<button class="copybtn" type="button" title="copy the list with links">'
            f'⧉ copy list</button></div>'
            f'<ul class="copylist">{rows}</ul>'
            f'<pre class="copytext" hidden>{text}</pre></div>')


def pr_chip(num):
    """Inline `#N` chip with a live state dot, for prose fields like `prs:`."""
    request_pr(DEFAULT_REPO, num)
    smry = pr_summary(DEFAULT_REPO, num)
    url, title, state = pr_url(num), '', ''
    if smry and 'error' not in smry:
        url = smry['url']
        state = ('merged' if smry['merged'] else
                 'closed' if smry['closed'] else
                 'fail' if smry['fail'] else
                 'pending' if smry['pending'] else 'ok')
        title = f'{smry["title"]} · {state}'
    return (f'<a class="chip pr {state}" href="{html.escape(url)}" '
            f'title="{html.escape(title)}">#{num}</a>')


def decorate_prs(value):
    """Chip every `#N` and break the prose into one line per group, splitting
    at sentence ends and at ` / ` dividers."""
    chip = lambda m: pr_chip(int(m.group(1)))
    segs = [seg for part in html.escape(value).split(' / ')
            for seg in re.split(r'(?<=\.)\s+(?=\S)', part) if seg.strip()]
    return ''.join(f'<div>{PR_NUM_RE.sub(chip, seg.strip())}</div>' for seg in segs)


def comment_rows(num):
    entry = comment_cache.get((DEFAULT_REPO, num))
    if entry is None:
        return '<p class="cmt">comments loading…</p>'
    if 'error' in entry:
        return '<p class="cmt">comments unavailable</p>'
    if not entry['data']:
        return '<p class="cmt">no human comments found</p>'
    rows = []
    for c in entry['data'][-3:]:
        body = c['body'][:300] + ('…' if len(c['body']) > 300 else '')
        where = (f' on <code>{html.escape(c["path"].rsplit("/", 1)[-1])}</code>'
                 if c['path'] else '')
        when = (f'<a href="{html.escape(c["url"])}">{html.escape(c["created"])}</a>'
                if c['url'] else html.escape(c['created']))
        rows.append(f'<p class="cmt"><span class="who">{html.escape(c["author"])}'
                    f'</span>{where} ({when}): “{html.escape(body)}”</p>')
    return ''.join(rows)


def render_nvim(proj):
    """Per-PR Diffview commands from the `## nvim` section, each scoped to its lane step."""
    rows = []
    for num, cmd in proj['nvim']:
        smry = pr_summary(DEFAULT_REPO, num) or {}
        url = smry.get('url') or f'https://github.com/{DEFAULT_REPO}/pull/{num}'
        rows.append(f'<li><a class="prnum" href="{html.escape(url)}" data-pr="{num}">#{num}</a>'
                    f'<code class="nvimcmd">{html.escape(cmd)}</code></li>')
    cwd = proj['nvim_cwd']
    cwd_html = f'<div class="cwd">cd {html.escape(cwd)} &amp;&amp; nvim</div>' if cwd else ''
    text = html.escape('\n'.join(
        ([f'cd {cwd} && nvim'] if cwd else []) + [cmd for _num, cmd in proj['nvim']]))
    return (f'<div class="copybox"><div class="copyhead">nvim diffs'
            f'<span class="count">{len(rows)}</span>'
            f'<button class="copybtn" type="button" title="copy every command">'
            f'⧉ copy all</button></div>{cwd_html}'
            f'<ul class="copylist">{"".join(rows)}</ul>'
            f'<pre class="copytext" hidden>{text}</pre></div>')


def render_needs_action(proj):
    items = [(lane, node.num) for lane, node in lane_nodes(proj['lanes'])
             if node.attention and not is_merged(pr_summary(DEFAULT_REPO, node.num))]
    if not items:
        return ''
    rows = []
    for lane, num in items:
        request_comments(DEFAULT_REPO, num)
        smry = pr_summary(DEFAULT_REPO, num)
        smry = smry if smry and 'error' not in smry else {}
        note = proj['actions'].get(num)
        ctx = (html.escape(note).replace('Recommendation:',
                                         '<b>Recommendation:</b>', 1) if note else
               f'no context yet: add a <code>- #{num}:</code> bullet under '
               f'<code>## Needs action</code>')
        rows.append(
            f'<div class="arow"><span class="lanetag">{html.escape(lane)}</span>'
            f'<a class="prnum" href="{html.escape(smry.get("url") or pr_url(num))}">'
            f'#{num}</a>'
            f'<span class="prtitle">{html.escape(smry.get("title", ""))}</span></div>'
            f'{comment_rows(num)}<p class="ctx">{ctx}</p>')
    return (f'<div class="copybox action"><div class="copyhead">Needs action'
            f'<span class="count">{len(items)}</span></div>{"".join(rows)}</div>')


def render_pr_section(fields):
    refs = pr_refs(fields)
    if not refs:
        return ''
    lines = []
    for repo, num in refs:
        request_pr(repo, num)
        smry = pr_summary(repo, num)
        if smry is None:
            lines.append(f'<li><span class="dot warn"></span>#{num} · state loading…</li>')
            continue
        if 'error' in smry:
            lines.append(f'<li><span class="dot warn"></span>#{num} · state unavailable: '
                         f'{html.escape(smry["error"][:100])}</li>')
            continue
        kind = ('crit' if smry['fail'] else
                'warn' if smry['pending'] and not smry['merged'] else 'good')
        bits = [f'<a href="{html.escape(smry["url"])}">#{num}</a>',
                html.escape(smry['title'])]
        if smry['merged']:
            bits.append('<b>merged</b>')
        elif smry['draft']:
            bits.append('draft')
        checks = f'{smry["ok"]}✓'
        if smry['fail']:
            checks += f' {smry["fail"]}✗'
        if smry['pending']:
            checks += f' {smry["pending"]}…'
        bits.append(checks)
        if smry['review']:
            bits.append(smry['review'])
        lines.append(f'<li><span class="dot {kind}"></span>{" · ".join(bits)}</li>')
    return f'<ul class="prlist">{"".join(lines)}</ul>'


def render_attention(projects):
    items = []
    for proj in projects:
        f, stem = proj['fields'], proj['file'].stem
        name = f'<a href="{project_href(stem)}">{html.escape(proj["title"])}</a>'
        found = []
        blockers = f.get('blockers', '')
        if is_set(blockers):
            found.append(('crit', f'blocked: {decorate(blockers)}'))
        days, staleness_kind, _ = proj['staleness']
        if staleness_kind != 'good':
            found.append((staleness_kind, f'no update in {days}d'))
        for repo, num in pr_refs(f):
            smry = pr_summary(repo, num)
            if not smry or 'error' in smry or is_closed_or_merged(smry):
                continue
            pr = f'PR <a href="{html.escape(smry["url"])}">#{num}</a>'
            if smry['fail']:
                found.append(('crit', f'{pr} · {smry["fail"]} check(s) failing'))
            elif smry['ready']:
                found.append(('good', f'{pr} · green, awaiting merge'))
        for _name, node in lane_nodes(proj.get('lanes', [])):
            if not node.attention:
                continue
            smry = pr_summary(DEFAULT_REPO, node.num)
            # A merged or closed PR cannot need a reply, whatever the `!`
            # marker in the status file still says.
            if is_closed_or_merged(smry):
                continue
            url = (smry.get('url') if smry else None) or pr_url(node.num)
            found.append(('warn', f'PR <a href="{html.escape(url)}">#{node.num}</a>'
                                  f' · {ATTENTION_NOTE}'))
        items += [f'<li><span class="dot {kind}"></span>{name} · {msg}</li>'
                  for kind, msg in found]
    if not items:
        return ''
    return f'<div class="attn"><h2>needs you</h2><ul>{"".join(items)}</ul></div>'


def qparam(query, name='p'):
    return (query.get(name) or [''])[0]


def project_href(stem, **extra):
    return f'/project?{urlencode({"p": stem, **extra})}'


def render_project(board_dir, query):
    path = find_status(board_dir, qparam(query))
    if path is None:
        return None
    proj = parse_status_file(path)
    f = proj['fields']

    rows = [(k, decorate_prs(f[k]) if k == 'prs' else decorate(f[k]))
            for k in ROW_FIELDS if is_set(f.get(k))]
    rows += [(k, decorate(v)) for k, v in f.items()
             if k not in KNOWN_FIELDS and is_set(v) and not is_video(k, v)]
    if proj['plan']:
        rows.append(('plan', f'<a href="/file?{urlencode({"p": proj["plan"]})}">'
                             f'{html.escape(proj["plan"])}</a>'))
    if proj['log']:
        rows.append(('log', f'<a href="/log?{urlencode({"p": path.stem})}">'
                            f'{len(proj["log"])} entries</a>'))
    dl = ''.join(f'<dt>{html.escape(FIELD_LABELS.get(k, k))}</dt><dd>{v}</dd>'
                 for k, v in rows)

    body = [f'<div class="badges">{badges_for(proj)}{poc_doc_button(f)}</div>']
    if dl:
        body.append(f'<dl>{dl}</dl>')
    if proj['lanes']:
        body.append(render_lanes(proj['lanes'], path.stem))
        panels = render_reviewable(proj['lanes']) + render_needs_action(proj)
        if panels:
            body.append(f'<div class="panels">{panels}</div>')
        if proj['nvim']:
            body.append(render_nvim(proj))
    else:
        prs = render_pr_section(f)
        if prs:
            body.append(f'<div class="laneshead">PRs'
                        f'{refresh_button(path.stem)}</div>{prs}')
    if proj['steps']:
        body.append(render_view_metro(proj))
    else:
        body.append(f'<p class="empty">No steps yet — add a <code>## Steps</code> '
                    f'checkbox list to {html.escape(str(path))}</p>')
    videos = [(k, v) for k, v in f.items() if is_set(v) and is_video(k, v)]
    if videos:
        body.append('<div class="laneshead">Video</div><div class="clips">' + ''.join(
            f'<figure class="clip"><video controls preload="metadata" '
            f'src="/media?{urlencode({"p": v})}"></video>'
            f'<figcaption>{html.escape(k)} · {html.escape(v)}</figcaption></figure>'
            for k, v in videos) + '</div>')
    if proj['desc']:
        body.append(render_desc(proj['desc']))

    sub = (f'<a href="/">← projects</a> · {html.escape(str(path))}'
           f'{project_buttons(path, proj)}')
    return page(proj['title'], sub, ''.join(body), script=JS)


def render_desc(entries):
    """Description paragraphs, with structure: `• ` lines indent as list rows,
    and a line introducing bullets (or ending with a colon) becomes a small
    group heading."""
    out = []
    for i, p in enumerate(entries):
        if p.startswith('• '):
            out.append(f'<p class="descli">{decorate(p)}</p>')
        elif p.endswith(':') or (i + 1 < len(entries) and entries[i + 1].startswith('• ')):
            out.append(f'<p class="deschead">{decorate(p)}</p>')
        else:
            out.append(f'<p>{decorate(p)}</p>')
    return f'<div class="desc">{"".join(out)}</div>'


def project_buttons(path, proj):
    """Header actions: mark shipped (active projects) and archive/unarchive."""
    actions = []
    in_archive = path.parent.name == 'archive'
    if not in_archive and proj['phase_label'] not in TERMINAL_PHASES:
        actions.append(('/mark-shipped', '⚑ shipped', 'set phase: shipped'))
    actions.append(('/unarchive', '⇡ unarchive', 'move back onto the board')
                   if in_archive else
                   ('/archive', '⇣ archive', 'move into archive/'))
    stem = html.escape(path.stem)
    return ''.join(
        f'<button class="boardbtn" type="button" data-stem="{stem}" '
        f'data-action="{action}" title="{title}">{label}</button>'
        for action, label, title in actions)


def render_log(board_dir, query):
    path = find_status(board_dir, qparam(query))
    if path is None:
        return None
    proj = parse_status_file(path)
    if not proj['log']:
        return None
    entries = ''.join(f'<div class="logentry"><h3>{html.escape(k)}</h3>'
                      f'<p>{decorate(v)}</p></div>' for k, v in proj['log'])
    sub = (f'<a href="{project_href(path.stem)}">← {html.escape(proj["title"])}</a>'
           f' · {html.escape(str(path))}')
    return page(f'{proj["title"]} · log', sub,
                f'<div class="log">{entries}</div>', script=JS)


def resolve_home_file(raw):
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except OSError:
        return None
    if not path.is_file() or not path.is_relative_to(Path.home().resolve()):
        return None
    return path


def render_file(query):
    path = resolve_home_file(qparam(query))
    if path is None:
        return None
    try:
        text = path.read_text(errors='replace')
    except OSError:
        return None
    sub = f'<a href="/">← projects</a> · {html.escape(str(path))}'
    return page(path.name, sub, f'<pre>{html.escape(text)}</pre>')


def page(title, sub, body, script=''):
    script_tag = f'<script>{script}</script>' if script else ''
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head>'
            f'<body><header><h1>{html.escape(title)}</h1>'
            f'<span class="sub">{sub}</span></header>'
            f'<main>{body}</main>{script_tag}</body></html>')


def rename_lane(board_dir, stem, old, new):
    """Rename a `- old:` lane bullet inside the ## Lanes section. True on success."""
    new = new.strip().replace(':', '').replace('\n', ' ')
    path = find_status(board_dir, stem)
    if path is None or not re.fullmatch(r'[\w][\w -]*', new):
        return False
    lines, in_lanes, done = path.read_text().splitlines(keepends=True), False, False
    for i, line in enumerate(lines):
        if line.startswith('## '):
            in_lanes = line[3:].strip().lower() == 'lanes'
        elif in_lanes and re.match(rf'-\s+{re.escape(old)}:', line):
            lines[i] = re.sub(rf'^(-\s+){re.escape(old)}:',
                              rf'\g<1>{new}:', line, count=1)
            done = True
            break
    if done:
        path.write_text(''.join(lines))
    return done


def mark_shipped(board_dir, stem):
    """Rewrite the `- phase:` meta bullet to shipped and bump last-updated."""
    path = find_status(board_dir, stem)
    if path is None:
        return False
    text = path.read_text()
    new, n = re.subn(r'(?m)^(-\s+phase:\s*).*$', r'\g<1>shipped', text, count=1)
    if not n:
        return False
    new = re.sub(r'(?m)^(-\s+last-updated:\s*).*$',
                 rf'\g<1>{date.today().isoformat()}', new, count=1)
    path.write_text(new)
    return True


POST_ROUTES = {
    '/lane-rename': lambda d, req: rename_lane(d, str(req['p']),
                                               str(req['old']), str(req['new'])),
    '/refresh': lambda d, req: refresh_now(d, str(req.get('p') or '')),
    '/archive': lambda d, req: move_project(d, str(req['p'])),
    '/unarchive': lambda d, req: move_project(d, str(req['p']), unarchive=True),
    '/mark-shipped': lambda d, req: mark_shipped(d, str(req['p'])),
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        route = POST_ROUTES.get(urlparse(self.path).path)
        if route is None:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            req = json.loads(self.rfile.read(length)) if length else {}
            ok = route(self.board_dir, req)
        except (ValueError, KeyError, OSError):
            ok = False
        data = json.dumps({'ok': ok}).encode()
        self.send_response(200 if ok else 400)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/media':
            self.serve_media(query)
            return
        if url.path == '/':
            body = render_index(self.board_dir)
        elif url.path == '/shipped':
            body = render_group(self.board_dir)
        elif url.path == '/archived':
            body = render_group(self.board_dir, archived=True)
        elif url.path == '/project':
            body = render_project(self.board_dir, query)
        elif url.path == '/log':
            body = render_log(self.board_dir, query)
        elif url.path == '/file':
            body = render_file(query)
        else:
            body = None
        if body is None:
            self.send_error(404)
            return
        data = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_media(self, query):
        path = resolve_home_file(qparam(query))
        ctype = VIDEO_TYPES.get(path.suffix.lower()) if path else None
        if not ctype:
            self.send_error(404)
            return
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get('Range', '')
        m = re.match(r'bytes=(?=\d|-\d)(\d*)-(\d*)$', rng)
        if rng and not m:
            self.send_error(416)
            return
        if m:
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:  # suffix range: the last N bytes
                start = max(0, size - int(m.group(2)))
            if start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.end_headers()
                return
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        else:
            self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers()
        with path.open('rb') as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break  # the player aborts range requests routinely
                remaining -= len(chunk)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--port', type=int, default=7788)
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--archive', metavar='SLUG',
                    help='move SLUG.md into archive/ and exit')
    args = ap.parse_args()
    board_dir = BOARD_DIR
    if args.archive:
        if not move_project(board_dir, args.archive):
            raise SystemExit(f'no status file {board_dir / (args.archive + ".md")} '
                             f'(or archive/ already has one)')
        print(f'archived {args.archive}.md to archive/')
        return
    Handler.board_dir = board_dir
    load_pr_cache()
    threading.Thread(target=poll_prs, args=(Handler.board_dir,),
                     daemon=True).start()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}/'
    print(f'projects board at {url} (ctrl-c to stop)')
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
