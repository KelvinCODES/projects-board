# <branch-name>

- phase: poc
- milestone: <Linear project name> (team <Linear team>)
- branch: <branch-name> (base master <sha>)
- worktree: ~/code/moveworks-wt/<branch-name>
- prs: none yet
- blockers: none
- last-updated: <YYYY-MM-DD>

<One short paragraph: what the feature is and how it's gated (FP name).>

Detail plan: <path to the plan markdown>

## Steps

- [ ] <major step>
  - [ ] <sub-step>

<!--
Format rules (the board at board.py renders this file):
- phase: ONE word, from the pipeline vocabulary: poc | spec | tickets |
  implementing | converging | regression | done. Progress narrative belongs
  in ## Steps, never on this line.
- prs / blockers: `none` (or `none yet`) means empty; anything else shows
  as content, and any non-none blockers mark the project blocked.
- last-updated: ISO date, bump on every edit.
- Steps: `[x]` done, `[~]` in progress, `[ ]` todo; two-space indent nests
  sub-steps. Exactly one `[~]` at a time is the convention. While a step is
  in progress, keep a live sub-checklist nested under it (what's done, what
  you're on, what's left inside the step) and update it as you work.
- Evidence bullets, added by the pipeline as they appear:
  `- video-poc: <path>`, `- poc-evidence: <path>`, `- video: <path>`.
  Video paths must live under $HOME; recordings go in videos/. The
  `./record <branch-name> poc|verify` helper records, names, and appends for you.
- `phase: done` folds the project into the index's done row;
  `board.py --archive <branch-name>` moves the file into archive/ (still viewable).
- Extra `- key: value` bullets are allowed and render as meta rows.
- Files starting with `_` are ignored by the board.
-->
