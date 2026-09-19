# <branch-name>

- phase: poc
- milestone: <Linear project name> (team <Linear team>)
- branch: <branch-name>
- worktree: ~/code/moveworks-wt/<branch-name>
- prs: none yet
- blockers: none
- last-updated: <YYYY-MM-DD>

Tested:

<Surface or feature name>

- <check> → <observed result>

Detail plan: <path to the plan markdown>

## Steps

- [ ] POC
- [ ] Verify
- [ ] Spec & Tickets
  - spec: ~/code/moveworks-kb/specs/<branch-name>.md
- [ ] Implement
- [ ] Converge
- [ ] Regression
- [ ] Ship
- [ ] Cleanup

<!--
Format rules (the board at board.py renders this file):
- phase: ONE word, from the pipeline vocabulary: poc | spec | tickets |
  implementing | converging | regression | paused | done | shipped. Progress
  narrative belongs in ## Steps, never on this line. paused parks a project in
  the index's last section and out of the needs-you rail; say why in a
  `- paused:` bullet. done and shipped both fold the project into the index's
  done row (the board's "⚑ shipped" button writes shipped).
- prs / blockers: `none` (or `none yet`) means empty; anything else shows
  as content, and any non-none blockers mark the project blocked.
- Description (the free lines above Detail plan): ONLY the `Tested:` block,
  filled from the live verify — bullets grouped under plain surface/feature
  lines (Group DM / Channel / 1:1 DM ...), matching the poc video's order,
  one `<check> → <result>` bullet per row, the same grouping as the
  go/no-go package. The go/no-go decision lives on its Steps entry,
  `- [x] go/no-go: <verdict> (<date>) <doc path>` (the KB markdown path;
  the spec written in the same step sits beside it as `- spec: <specs path>`;
  the board's go/no-go button opens it in Obsidian), never in the description. What the feature is lives in the title
  and meta rows; mechanism prose lives in the plan or the log.
  Plain `- ` bullets render as desc lines, while a bullet starting `word:`
  becomes a meta row, so lead each bullet with the check itself.
- last-updated: ISO date, bump on every edit.
- lane: 1, 2 or 3, which live-test stack this project has claimed (local-bot-session
  skill, *Lanes*); set before the first botsync, check sibling files first.
- Steps: `[x]` done, `[~]` in progress, `[ ]` todo; two-space indent nests
  sub-steps. Exactly one `[~]` at a time is the convention. While a step is
  in progress, keep a live sub-checklist nested under it (what's done, what
  you're on, what's left inside the step) and update it as you work.
- Top-level steps are the FIXED stations, same order for every project:
  POC / Verify / Spec & Tickets / Implement / Converge / Regression /
  Ship / Cleanup. Detail lives only in nested sub-checklists: optional
  research nests under POC; bazel + lint, the live e2e, the recorded clip,
  and the POC commit nest under Verify; the go/no-go gate closes
  Spec & Tickets; PRs open under Implement; CI-green + reviewer-quiet under
  Converge; merge/land under Ship. Never invent a new top-level station.
- ## Lanes (optional): `- <name>: #A -> #B -> ~#C (note)` bullets chain PRs; `#C(+a/-b)` pins a
  chip's own delta when GitHub's count is the whole lane (a join PR with two open parents). A join
  PR appears once, at the end of the lane whose code reaches it last; the other lane ends at its
  own last PR with a note `(feeds the join #C)`. Blocked is not parked: the dependency line
  already outlines the chip red (dotted for one open parent, solid for two or more)
  into lanes. `~#N` = parked; `!#N` = a human commented and it needs a reply
  (yellow dotted chip + a "needs you" row on the index); remove the `!`
  once answered. Each PR's branch and base show live from GitHub in the
  chip tooltip.
- ## nvim (optional): one Diffview command per open PR, scoped to that PR's
  own lane step: `- cwd: <worktree>` once, then `- #<num>: DiffviewOpen
  <parent>...<head>` where `<parent>` is the lane's previous branch (or
  `origin/master` for a lane root) and `<head>` the PR branch. Renders as an
  "nvim diffs" panel with a copy-all button. Write it when the PRs open and
  keep it in step with the Lanes section.
- ## Log (optional): session history as `- <date> <title>: <text>` bullets.
  The project page shows only a "log: N entries" link; keep long narratives
  here, never as meta bullets in the header.
- ## Needs action (optional): pairs with `!` lane markers. One bullet per
  flagged PR: `- #<num>: <two-sentence context> Recommendation: <one
  sentence>`. Renders as a yellow "Needs action" panel beside "Reviewable
  now", together with the PR's human comments fetched live from GitHub.
  Write the bullet when you set the `!`; delete both once handled.
- branch: just the worktree branch name; per-PR branches and shas live on
  GitHub, never in meta bullets.
- Evidence bullets, added by the pipeline as they appear:
  `- video-poc: <path>`, `- poc-evidence: <path>`, `- video: <path>`.
  Video paths must live under $HOME; recordings go in videos/. The
  `./record <branch-name> poc|verify` helper records, names, and appends for you.
- `phase: done` folds the project into the index's done row;
  `board.py --archive <branch-name>` moves the file into archive/ (still viewable).
- Extra `- key: value` bullets are allowed and render as meta rows.
- Files starting with `_` are ignored by the board.
-->
