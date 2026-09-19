# Dashboard orchestration design

Status: proposed architecture and interactive layout. The existing application has not been changed.

Design updated September 4, 2026. The interactive proposal is in orchestration-layout.html. The prioritized feature inventory and acceptance criteria are in [feature-backlog.md](feature-backlog.md).

## Visual and interaction direction

Use a compact workspace with persistent sidebar navigation, a quiet top bar, restrained accent color, clear typography, and light/dark themes. Keep the operational run view as a task list beside an agent inspector, with a concise orchestrator summary and a contextual guidance input above it. Use status labels, timestamps, dependency reasons, and observed activity to explain what is happening.

The updated preview starts on an active run. It includes quick navigation with a command menu, project-scoped launch, editable role overrides, a captured configuration for each queued preview run, guidance entries in the activity feed, contextual decisions/evidence/output, and decision state changes. All data and interactions are local preview state. Model jobs, guidance delivery, approval execution, and metrics ingestion still require the runner implementation.

Provide Indigo and Graphite accent options and Comfortable and Compact density options in the design controls. In the app, preserve drafts and selections during updates, use keyboard-accessible controls, honor reduced motion, and show clear empty, stale, disconnected, and interrupted states. Do not rely on animation or color alone for runtime status.

## Decision

Add shared navigation for Projects, Runs, Configurations, and Metrics. Keep the current project page as the home for a project's intent, pipeline progress, PR lanes, evidence, and history. Put execution detail on a run page. Put the prompt composer on a dedicated New run page, reachable globally and from a project.

The actual repository is /Users/kelvin.kong/.claude/projects-board.

| Location | Responsibility |
| --- | --- |
| Projects, existing / | Portfolio health, needs-action items, active run counts, links to shipped and archived projects |
| Project, existing /project?p=slug | Project context, fixed workflow stations, PR lanes, evidence, compact active-run summary, run history |
| Runs, proposed /runs | Cross-project execution list, filters for project/status/configuration, running and waiting work |
| Run, proposed /run?id=run-id | Orchestrator activity, tasks and dependencies, agent assignments, event timeline, artifacts, decisions, execution controls, usage |
| New run, proposed /runs/new?p=slug | Prompt, project/repository, workflow, saved configuration, orchestrator selection, optional role overrides and limits |
| Configurations, proposed /configurations | Versioned presets, role defaults, runtime inventory, model/effort capability checks |
| Metrics, proposed /metrics | Historical execution, quality, time, token, and cost analysis with project/run/model/role/configuration filters |
| Existing /log, /shipped, /archived, /file, /media | Preserve their current purposes and links |

The shared New run action opens the same composer everywhere. Starting from a project preselects that project. A dedicated composer has room for role overrides and validation while keeping the project detail readable.

## Terms and ownership

- Project: the durable outcome, repository context, status summary, PRs, and evidence. Its existing Markdown file remains authoritative for this human-facing view.
- Workflow: the skill and its phase/gate contract.
- Configuration: a reusable, versioned set of orchestrator, role, and execution choices.
- Run: one attempt to carry out a prompt under a resolved workflow and configuration. It belongs to a project and persists beyond a browser connection.
- Phase: one of the existing kelvin-implement stations.
- Task: a concrete unit of work within a run, with acceptance criteria and stable dependency IDs.
- Role: a responsibility and dispatch configuration, such as implementer or verifier. A role is not a permanent agent.
- Agent attempt: one actual worker/session assigned to a task, with a parent, role, runtime, model, effort, worktree, status, and usage.
- Orchestrator: the agent that owns the plan, delegation, synthesis, and decisions for a run. It is an agent attempt with a distinguished role.

Hierarchy: Project → Runs → Tasks → Agent attempts. Agents may have parent agents, and tasks may depend on other tasks. Retrying a task creates a new attempt while preserving the task and its previous outcomes.

Do not make a separate top-level Agents or Orchestrators page initially. Runs gives the cross-project operational view; run detail gives the agent tree; Configurations owns reusable team definitions.

## New run

Keep the default surface compact:

1. Prompt textarea.
2. Project and repository/working directory.
3. Workflow, initially kelvin-implement.
4. Saved configuration.
5. Orchestrator runtime, model, and effort.
6. Expandable role overrides and execution limits.
7. Resolved configuration summary and Start run.

The runtime is the installed program, such as Claude CLI or Codex CLI. The model is the model that program can actually access. Installed CLIs do not establish locally installed model weights or account entitlements.

Show only supported effort values for the selected runtime/model, with explicit Inherit behavior. Show the inherited value and its source. A runtime-default alias remains an alias until the runtime reports the actual model.

Execution choices should include maximum active workers, worktree policy, token budget, and optional runtime or cost limits. Label limits according to enforcement capability. Usage reported only at the end of a turn cannot support an exact instantaneous token cutoff. Cost limits require a configured price source and telemetry coverage.

Validate project/repository existence, runtime availability, role dispatch support, and configuration compatibility before creating a runnable job. Preserve the form on validation failure and on periodic status updates.

Snapshot the prompt, requested and resolved configuration, configuration version, workflow source/hash, CLI version, repository revision, and working directory. Preserve requested versus observed model/effort. Later preset edits affect future runs.

## Workflow and roles

Keep the current stations: POC → Verify → Spec & Tickets → Implement → Converge → Regression → Ship → Cleanup.

| Role slot | Responsibility | Initial default |
| --- | --- | --- |
| Orchestrator | Plan, dependency graph, delegation, synthesis, phase transitions, fix-or-decline decisions | Chosen at launch |
| Researcher / POC builder | Explore the code, prove the approach, produce an initial diff | Inherit orchestrator |
| Spec and ticket planner | Acceptance criteria and dependency-aware slices | Orchestrator |
| Implementer | One ready ticket in an isolated worktree | Claude / Opus, inherited effort |
| Verifier | Targeted tests, live verification, regression checks, evidence | Inherit orchestrator |
| Reviewer | Standards/spec reviews and local review-bot replica | Inherit applicable review configuration |
| Independent adjudicator | Read-only second opinion on ticket structure and review findings | Codex, configured model |
| PR / fix author | Draft PRs and execute fixes already decided by the orchestrator | Claude / Opus, inherited effort |

These are configuration slots. Instantiate agents when work requires them; eight role slots do not imply eight simultaneous agents. An orchestrator-owned role can execute in the orchestrator session. Giving it an explicit worker override delegates its artifact production while the orchestrator retains decision ownership.

Use separate reviewer task assignments for independent review perspectives. Independence must come from separate context and responsibilities, even when two reviewers use the same model.

The current skill hardcodes Opus for implementers and fix/PR authors, with inherited effort. The runtime integration must make any launch overrides explicit in the run-scoped workflow contract and dispatcher. A UI value cannot silently contradict the skill instructions.

Preserve the skill's go/no-go after the verified POC and concrete spec/ticket package. Show its evidence, exact proposed next action, and pending decision on the run page and in the project needs-action summary. Scope approval to the run and reviewed package. A reusable preset does not approve future work.

## Run detail

Header: project, run title, state, phase, elapsed wall time, active agent count, token usage, and configuration snapshot.

Orchestrator summary: current observable action, latest concise progress report, active dependencies, next intended step, latest activity timestamp, and any decision required.

Main area: task list/dependency graph and event timeline. Each task shows its stable ID, assigned agent/role, model, state, dependency or waiting reason, current action, elapsed time, and evidence.

Selecting an agent opens its inspector: parent agent, task, runtime/session identity, requested and actual model/effort, worktree, heartbeat, current tool/action, tokens, result, and scoped output.

Separate waiting reasons: human decision, task dependency, CI/external check, permission request, provider rate limit, unavailable runtime, or lost runner. Lack of recent output should show stale/unknown status rather than automatically claiming completion or failure.

Capture observable actions, tool calls, outputs, decisions, and concise progress summaries. The design does not depend on access to hidden model reasoning.

Controls: cancel run, retry a failed task as a new attempt, respond to a supported decision/permission request, and resume when the runtime supports it. Expose pause only when it has defined semantics, such as pausing new dispatch; suspending an OS process is not a complete workflow pause.

Distinguish UI lifecycle from process lifecycle. Closing the browser must not cancel work. Cancelling a run must stop its registered child processes, record the outcome, and retain worktrees and evidence. Cleanup follows the existing merged/clean/no-open-PR guards.

## Metrics

| Question | Metric |
| --- | --- |
| What is happening now? | Active runs, agents and tasks, concurrency, waiting reasons, last activity |
| Is work finishing? | Completed/failed/cancelled runs, task throughput, retry count, success rate with explicit denominator |
| Where does time go? | Wall time, active time, human wait, CI wait, queue time, phase duration, median and p95 |
| Where do tokens go? | Input/output, cache read/write where available, tokens by project/run/phase/role/model/configuration |
| What did it cost? | Estimated cost with dated price source, reported cost with provenance, budget consumption, telemetry coverage |
| Is the result improving? | First-pass check success, convergence passes, review findings resolved, rework after review, time to reviewable PR |
| Are workers stuck? | Stale heartbeat, repeated failures, rate-limit waits, orphaned sessions, long-blocked dependencies |

The Metrics page is historical and aggregate. A run page shows that run's usage; a project page links to Metrics with the project filter already applied.

Keep wall duration separate from aggregate agent active duration, since concurrent agent durations can exceed elapsed run time. Distinguish cached from uncached tokens using provider semantics, and normalize cumulative counters into deltas before summing.

Missing usage is Unknown, not zero. Show coverage and partial totals. Do not double-count a parent total that includes child usage. Do not present estimated API-equivalent cost as a subscription bill. Compare configurations within similar task/workflow groups and alongside completion/rework outcomes.

There is no existing run telemetry to backfill accurate historical token or runtime metrics. Historical project Markdown can provide project summaries, but it cannot manufacture missing process data.

## Python implementation shape

Keep board.py as the HTTP/UI entry point. Introduce an orchestration module with a small interface for discovering capabilities, validating and launching a run, fetching state/events, and applying supported controls. Both global and project-scoped pages call that interface.

Place runtime-specific behavior behind adapters for Claude and Codex. Each adapter owns argument construction, capability handling, process/session lifecycle, event parsing, usage normalization, and cancellation semantics. Cross-provider role dispatch must launch the selected runtime as a registered child of the run.

Use a local SQLite store for configurations, runs, tasks, dependency edges, agent attempts, events, usage samples, artifacts, and decisions. Every record carries stable project/run/task/attempt linkage where applicable. Store runtime data outside the root project Markdown glob, for example under a dedicated local data directory.

Persist run creation before dispatch, prevent duplicate launches with an idempotency key, and append ordered events with unique IDs. Retain raw provider events when useful for debugging and reprocessing, alongside normalized events. Never store authentication secrets in run snapshots or render them in logs.

A worker/supervisor owns durable dispatch and process bookkeeping. The HTTP request should enqueue and return a run ID, not block for a model job. On restart, reconcile active processes/sessions and mark unresolved attempts interrupted or unknown. Avoid silently launching a duplicate worker.

Use polling of narrow status fragments or a resumable event stream. The existing 15-second replacement of all main content would erase prompt/configuration drafts and disturb the event inspector. Do not apply whole-page refresh to editable or inspected runtime surfaces.

Run task completion and project phase completion are separate. Project updates follow verified workflow transitions. The existing project template allows exactly one active top-level station; parallel tasks belong in runtime records.

Keep the server bound to localhost. Mutation endpoints should validate origin and use a local session/CSRF token, require structured arguments, and avoid shell interpolation. Build subprocess argument arrays from validated configuration. Respect existing runtime permissions and workflow approvals.

Implementation checks should exercise real behavior through the orchestration interface: invalid/unsupported configuration, durable launch and duplicate suppression, concurrent task dependencies, role override dispatch, event/usage normalization, cancellation of children, restart reconciliation, and missing telemetry. UI checks should confirm prompt drafts survive live updates and project/run links preserve scope.

## Local integration points and sources

- board.py:1438, shared page shell and navigation.
- board.py:649, project cards.
- board.py:1315, project detail.
- board.py:1482 and board.py:1510, mutation and route dispatch.
- board.py:286, current whole-main refresh.
- board.py:425 and board.py:457, project Markdown discovery and loading.
- board.py:472, step parsing without stable task IDs.
- _template.md:49 and _template.md:54, active-station rule and fixed pipeline.
- /Users/kelvin.kong/.claude/skills/kelvin-implement/SKILL.md:36, POC and verification.
- /Users/kelvin.kong/.claude/skills/kelvin-implement/SKILL.md:55, go/no-go package.
- /Users/kelvin.kong/.claude/skills/kelvin-implement/SKILL.md:88, independent implementers and defaults.
- /Users/kelvin.kong/.claude/skills/kelvin-implement/SKILL.md:111, PR authors and review.
- /Users/kelvin.kong/.claude/skills/kelvin-implement/SKILL.md:150, convergence and decision ownership.
- /Users/kelvin.kong/.claude/skills/kelvin-implement/SKILL.md:204, cleanup guards.

Installed runtime commands were inspected using local help only. Claude and Codex were found on PATH; Gemini and Ollama were not. No model jobs were launched during this design pass.

Current capability references:

- [Claude subagent configuration](https://code.claude.com/docs/en/sub-agents)
- [Codex non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
