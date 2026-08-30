# projects-board

A live web view of the Claude Code projects I have running. Each project is one
markdown status file in this directory. The board re-reads them on every page
load, so the files stay the source of truth and nothing caches.

## Run

    ./board.py                                    # http://127.0.0.1:7788
    ./board.py --port 8000 --dir /other/dir --no-open

The page polls itself every 15 seconds and swaps in the new content, so a status
file edit shows up without a refresh.

## Files

    board.py       server, parser, and the HTML it renders. Standard library only.
    record         screen-records a demo and attaches it to a project's status file
    _template.md   the status file format, with the rules in its comment block

## Status file format

Full rules live in `_template.md`. The short version: `- key: value` bullets for
metadata, a `## Steps` checklist where `[x]` is done, `[~]` is in progress and
`[ ]` is todo, and a `Detail plan:` line pointing at a plan markdown file.

Status files are not tracked here, only the template.
