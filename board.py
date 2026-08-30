#!/usr/bin/env python3
"""Live web view of the status files in this directory.

Each *.md file is one project (`_`-prefixed files, like the format template
`_template.md`, are skipped): `- key: value` bullets (phase, branch,
milestone, prs, blockers, last-updated), free paragraphs as description, an
optional `Detail plan: <path>` line, a `## Steps` checkbox list —
`- [x]` done, `- [~]` in progress, `- [ ]` todo, indentation for sub-steps —
and any number of `- video: <path>` / `- video-<name>: <path>` bullets that
render as inline players (served with Range support so scrubbing works).
The index lists projects; clicking one shows its step tree. Stdlib only;
re-reads the files on every page load, so the files stay the source of truth.

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
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

BOARD_DIR = Path(__file__).resolve().parent
ROW_FIELDS = ('milestone', 'branch', 'worktree', 'prs', 'blockers')
VIDEO_TYPES = {'.mp4': 'video/mp4', '.mov': 'video/quicktime',
               '.webm': 'video/webm', '.m4v': 'video/x-m4v'}
DEFAULT_REPO = 'moveworks-emu/moveworks'
LINEAR_URL = 'https://linear.app/moveworks/issue/'
PR_URL_RE = re.compile(r'github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)')
PR_NUM_RE = re.compile(r'#(\d+)\b')
PR_JSON_FIELDS = 'title,url,state,isDraft,reviewDecision,statusCheckRollup'
PR_REFRESH_SECS = 60
pr_cache = {}  # (repo, number) -> {'data': ...} / {'error': ...} / None while fetching
KNOWN_FIELDS = set(ROW_FIELDS) | {'phase', 'last-updated'}
STEP_STATES = {'x': 'done', ' ': 'todo'}  # anything else (~, -, >, /) = wip

CSS = """
:root {
  color-scheme: light dark;
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --border: rgba(11,11,11,.10); --hairline: #e1e0d9;
  --good: #0ca30c; --warn: #fab219; --crit: #d03b3b;
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
        transition: border-color .12s, transform .12s; height: 100%; }
a.cardlink:hover .card { border-color: var(--muted); transform: translateY(-1px); }
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
.empty { color: var(--muted); }

/* project page */
dl { display: grid; grid-template-columns: max-content 1fr; gap: 3px 12px;
     margin: 0 0 20px; font-size: 13px; max-width: 780px; }
dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }
code, .chip { font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.chip { border: 1px solid var(--hairline); border-radius: 4px;
        padding: 0 4px; white-space: nowrap; text-decoration: none; }
a.chip:hover { border-color: var(--muted); }
.tree { margin: 4px 0 20px; }
.tree ul { list-style: none; margin: 0; padding-left: 22px; }
.tree li { position: relative; padding: 8px 0 0 22px; }
.tree li::before { content: ''; position: absolute; left: 0; top: 22px;
                   width: 18px; border-top: 2px solid var(--hairline); }
.tree li::after { content: ''; position: absolute; left: 0; top: 0; bottom: 0;
                  border-left: 2px solid var(--hairline); }
.tree li:last-child::after { height: 22px; bottom: auto; }
.node { display: inline-flex; align-items: center; gap: 8px; font-size: 13px;
        background: var(--surface); border: 1px solid var(--border);
        border-radius: 999px; padding: 3px 12px; box-shadow: var(--shadow); }
.node .glyph { flex: none; }
.node .lbl { min-width: 0; }
.node.done { border-color: var(--good);
             background: color-mix(in srgb, var(--good) 8%, var(--surface)); }
.node.done .glyph { color: var(--good); }
.node.wip { border-color: var(--warn);
            background: color-mix(in srgb, var(--warn) 12%, var(--surface)); }
.spinner { display: inline-block; vertical-align: -2px; width: 12px;
           height: 12px; border-radius: 50%; flex: none;
           border: 2px solid var(--hairline); border-top-color: var(--warn);
           animation: spin .9s linear infinite; }
.node.todo { color: var(--muted); }
.node.root { font-weight: 600; padding: 5px 14px; }
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

.views { display: flex; gap: 6px; margin: 4px 0 16px; }
.views a { text-decoration: none; font-size: 12px; color: var(--ink2);
           border: 1px solid var(--border); border-radius: 999px; padding: 2px 12px; }
.views a.active { border-color: var(--ink2); color: var(--ink); font-weight: 600; }

/* pipeline view */
.pipe { display: flex; flex-wrap: wrap; gap: 40px 44px; padding: 8px 0 20px; }
.stage { position: relative; max-width: 250px; }
.stage:not(:first-child)::before { content: ''; position: absolute; left: -44px;
  top: 14px; width: 44px; border-top: 2px solid var(--hairline); }
.kids { list-style: none; margin: 0; padding: 4px 0 0 12px; }
.kids li { position: relative; padding: 6px 0 0 16px; }
.kids li::before { content: ''; position: absolute; left: 0; top: 19px; width: 12px;
                   border-top: 2px solid var(--hairline); }
.kids li::after { content: ''; position: absolute; left: 0; top: 0; bottom: 0;
                  border-left: 2px solid var(--hairline); }
.kids li:last-child::after { height: 19px; bottom: auto; }
.kids .node { font-size: 12px; padding: 2px 10px; }

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

/* org chart view */
.org { overflow-x: auto; padding: 8px 0 16px; }
.org ul { display: flex; list-style: none; margin: 0; padding: 24px 0 0;
          position: relative; }
.org > ul { padding: 0; }
.org li { display: flex; flex-direction: column; align-items: center;
          position: relative; padding: 24px 8px 0; }
.org > ul > li { padding: 0; }
.org li::before, .org li::after { content: ''; position: absolute; top: 0;
  right: 50%; width: 50%; height: 24px; border-top: 2px solid var(--hairline); }
.org li::after { right: auto; left: 50%; border-left: 2px solid var(--hairline); }
.org li:only-child::before, .org li:only-child::after { display: none; }
.org > ul > li::before, .org > ul > li::after { display: none; }
.org li:first-child::before { border-top: none; }
.org li:last-child::after { border-top: none; }
.org ul::before { content: ''; position: absolute; top: 0; left: 50%; height: 24px;
                  border-left: 2px solid var(--hairline); }
.org > ul::before { display: none; }
.org .node { max-width: 190px; }

.clips { display: flex; flex-wrap: wrap; gap: 16px; margin: 4px 0 20px; }
.clip { margin: 0; }
.clip video { width: 480px; max-width: 100%; display: block; background: #000;
              border: 1px solid var(--border); border-radius: 8px; }
.clip figcaption { font-size: 12px; color: var(--muted); margin-top: 4px; }
.desc { max-width: 780px; }
.desc p { color: var(--ink2); font-size: 13px; }
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
    const cur = document.querySelector('main'), nxt = fresh.querySelector('main');
    if (cur && nxt && cur.innerHTML !== nxt.innerHTML) cur.innerHTML = nxt.innerHTML;
  } catch (e) {}
}
setInterval(() => { if (!document.hidden) refresh(); }, 15000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
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


def parse_status_file(path):
    proj = {'file': path, 'title': path.stem, 'fields': {}, 'desc': [],
            'plan': None, 'steps': []}
    key, para, stack = None, [], []

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
        if key and line[:1].isspace() and line.strip():
            proj['fields'][key] += ' ' + line.strip()
            continue
        key = None
        if m := re.match(r'-\s+([\w-]+):\s*(.*)', line):
            flush_para()
            key = m.group(1)
            proj['fields'][key] = m.group(2).strip()
        elif m := re.match(r'detail plan:\s*(.*)', line, re.IGNORECASE):
            flush_para()
            proj['plan'] = m.group(1).strip()
        elif line.startswith('# ') and not line.startswith('## '):
            flush_para()
            proj['title'] = line[2:].strip()
        elif line.strip() and not line.startswith('#'):
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


def leaves(nodes):
    for n in nodes:
        if n['children']:
            yield from leaves(n['children'])
        else:
            yield n


def current_step(ls):
    return (next((l for l in ls if l['state'] == 'wip'), None)
            or next((l for l in ls if l['state'] == 'todo'), None))


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


def render_index_card(proj):
    ls = list(leaves(proj['steps']))
    done = sum(l['state'] == 'done' for l in ls)
    parts = [f'<h3>{html.escape(proj["title"])}</h3>',
             f'<div class="badges">{badges_for(proj)}</div>']
    if ls:
        pct = round(100 * done / len(ls))
        parts.append(f'<div class="progress"><span class="bar">'
                     f'<i style="width:{pct}%"></i></span>'
                     f'<span class="count">{done}/{len(ls)} steps</span></div>')
    now = current_step(ls)
    if now:
        parts.append(f'<p class="nowline"><span class="spinner"></span> '
                     f'{decorate(now["label"], links=False)}</p>')
    href = project_href(proj['file'].stem)
    return f'<a class="cardlink" href="{href}"><article class="card">' \
           f'{"".join(parts)}</article></a>'


def render_index(board_dir):
    projects = sorted((parse_status_file(p) for p in status_files(board_dir)),
                      key=sort_key)
    active = [p for p in projects if p['phase_label'] != 'done']
    done = [p for p in projects if p['phase_label'] == 'done']
    if active:
        body = (render_attention(active) + '<div class="grid">'
                + ''.join(render_index_card(p) for p in active) + '</div>')
    else:
        body = f'<p class="empty">No active projects in {html.escape(str(board_dir))}</p>'

    def links(pairs):
        return ' · '.join(f'<a href="{project_href(stem)}">'
                          f'{html.escape(title)}</a>' for stem, title in pairs)

    if done:
        body += ('<p class="donebar">done: '
                 + links((p['file'].stem, p['title']) for p in done) + '</p>')
    archived = [parse_status_file(f) for f in status_files(board_dir, archived=True)]
    if archived:
        body += ('<p class="donebar">archived: '
                 + links((p['file'].stem, p['title']) for p in archived) + '</p>')
    sub = (f'{len(projects)} project(s) · {html.escape(str(board_dir))}'
           f' · rendered {datetime.now().strftime("%H:%M:%S")}')
    return page('Projects board', sub, body, script=JS)


def glyph_html(state):
    if state == 'wip':
        return '<span class="glyph spinner"></span>'
    return f'<span class="glyph">{"✓" if state == "done" else "○"}</span>'


def node_html(n):
    now = ' <span class="now">now</span>' if n['state'] == 'wip' else ''
    return (f'<span class="node {n["state"]}">{glyph_html(n["state"])}'
            f'<span class="lbl">{decorate(n["label"])}</span>{now}</span>')


def step_ul(nodes, cls=''):
    if not nodes:
        return ''
    attr = f' class="{cls}"' if cls else ''
    items = ''.join(f'<li>{node_html(n)}{step_ul(n["children"], cls)}</li>'
                    for n in nodes)
    return f'<ul{attr}>{items}</ul>'


def render_view_tree(proj):
    return (f'<div class="tree"><span class="node root">'
            f'{html.escape(proj["title"])}</span>'
            f'{step_ul(proj["steps"])}</div>')


def render_view_pipeline(proj):
    stages = ''.join(
        f'<div class="stage">{node_html(n)}{step_ul(n["children"], "kids")}</div>'
        for n in proj['steps'])
    return f'<div class="pipe">{stages}</div>'


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


def render_view_org(proj):
    return (f'<div class="org"><ul><li><span class="node root">'
            f'{html.escape(proj["title"])}</span>{step_ul(proj["steps"])}</li></ul></div>')


STEP_VIEWS = {'metro': ('metro', render_view_metro),
              'pipeline': ('pipeline', render_view_pipeline),
              'org': ('org chart', render_view_org),
              'tree': ('file tree', render_view_tree)}


def view_tabs(stem, active):
    tabs = []
    for key, (label, _) in STEP_VIEWS.items():
        cls = ' class="active"' if key == active else ''
        tabs.append(f'<a{cls} href="{project_href(stem, view=key)}">{label}</a>')
    return f'<nav class="views">{"".join(tabs)}</nav>'


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


def poll_prs(board_dir):
    while True:
        refs = set()
        for f in status_files(board_dir):
            try:
                refs.update(pr_refs(parse_status_file(f)['fields']))
            except OSError:
                pass
        todo = [ref for ref in refs if not is_settled(ref)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ref, entry in zip(todo, pool.map(lambda r: fetch_pr(*r), todo)):
                pr_cache[ref] = entry
        time.sleep(PR_REFRESH_SECS)


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
    return {'title': d.get('title', ''), 'url': d.get('url', ''),
            'draft': d.get('isDraft', False), 'merged': d.get('state') == 'MERGED',
            'review': (d.get('reviewDecision') or '').lower().replace('_', ' '),
            'ok': ok, 'fail': fail, 'pending': pending,
            'ready': (d.get('state') == 'OPEN' and not d.get('isDraft')
                      and ok > 0 and fail == 0 and pending == 0)}


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
            if not smry or 'error' in smry:
                continue
            pr = f'PR <a href="{html.escape(smry["url"])}">#{num}</a>'
            if smry['fail']:
                found.append(('crit', f'{pr} · {smry["fail"]} check(s) failing'))
            elif smry['ready']:
                found.append(('good', f'{pr} · green, awaiting merge'))
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

    rows = [(k, decorate(f[k])) for k in ROW_FIELDS if is_set(f.get(k))]
    rows += [(k, decorate(v)) for k, v in f.items()
             if k not in KNOWN_FIELDS and is_set(v) and not is_video(k, v)]
    if proj['plan']:
        rows.append(('plan', f'<a href="/file?{urlencode({"p": proj["plan"]})}">'
                             f'{html.escape(proj["plan"])}</a>'))
    dl = ''.join(f'<dt>{html.escape(k)}</dt><dd>{v}</dd>' for k, v in rows)

    body = [f'<div class="badges">{badges_for(proj)}</div>']
    if dl:
        body.append(f'<dl>{dl}</dl>')
    body.append(render_pr_section(f))
    if proj['steps']:
        view = qparam(query, 'view')
        if view not in STEP_VIEWS:
            view = next(iter(STEP_VIEWS))
        body.append(view_tabs(path.stem, view))
        body.append(STEP_VIEWS[view][1](proj))
    else:
        body.append(f'<p class="empty">No steps yet — add a <code>## Steps</code> '
                    f'checkbox list to {html.escape(str(path))}</p>')
    videos = [(k, v) for k, v in f.items() if is_set(v) and is_video(k, v)]
    if videos:
        body.append('<div class="clips">' + ''.join(
            f'<figure class="clip"><video controls preload="metadata" '
            f'src="/media?{urlencode({"p": v})}"></video>'
            f'<figcaption>{html.escape(k)} · {html.escape(v)}</figcaption></figure>'
            for k, v in videos) + '</div>')
    if proj['desc']:
        body.append('<div class="desc">'
                    + ''.join(f'<p>{decorate(p)}</p>' for p in proj['desc'])
                    + '</div>')

    sub = f'<a href="/">← projects</a> · {html.escape(str(path))}'
    return page(proj['title'], sub, ''.join(body), script=JS)


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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/media':
            self.serve_media(query)
            return
        if url.path == '/':
            body = render_index(self.board_dir)
        elif url.path == '/project':
            body = render_project(self.board_dir, query)
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
        src = board_dir / f'{args.archive}.md'
        if not src.is_file():
            raise SystemExit(f'no status file {src}')
        (board_dir / 'archive').mkdir(exist_ok=True)
        src.rename(board_dir / 'archive' / src.name)
        print(f'archived {src.name} to archive/')
        return
    Handler.board_dir = board_dir
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
