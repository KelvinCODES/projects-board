# Projects board feature backlog

Updated: September 4, 2026.

This is the local feature inventory for the dashboard and its proposed agent orchestration workspace. It is saved in the repository for future implementation and can be copied into Notion or an issue tracker later.

All features below describe production work that is still proposed. Some interactions are demonstrated with sample data in orchestration-layout.html. A working preview is not an implemented runner or source of real metrics.

Related design: [orchestration-plan.md](orchestration-plan.md).

## Product direction

Make it easy to answer four questions:

1. What work is moving across my projects?
2. What is the orchestrator doing, and which agents own each task?
3. What needs my decision or intervention?
4. Which configurations produce good results, and where do time and tokens go?

Use Projects for outcomes, Runs for execution, Configurations for reusable teams, and Metrics for analysis. Keep New run available globally and scoped to a project when opened from that project.

The modern visual direction is a compact sidebar, clear type hierarchy, quiet surfaces, a restrained accent, dense but readable rows, contextual inspectors, and keyboard access. Defaults should be useful before customization. Information and state transitions should stay understandable at a glance.

## Priority meaning

- P0, core: required for the requested launch/configure/observe workflow to behave correctly.
- P1, useful: improves control, visibility, or analysis once its supporting records exist.
- P2, exploratory: evaluate against actual usage and evidence before enabling.

Priority reflects product value, correctness, and dependencies. It is not an engineering timeline.

## P0: launch and trust the work

| ID | Feature and location | Why useful | Acceptance criteria |
| --- | --- | --- | --- |
| F01 | Shared workspace navigation and project links | Keeps the different pages coherent. | Projects, Runs, Configurations, and Metrics share navigation. Existing shipped/archive/log pages remain reachable. Project links preserve project scope. |
| F02 | Prompt composer, New run | Turns an intention into a concrete configured run. | Prompt, project/repository, workflow, preset, and orchestrator are visible. Validation preserves all input. Starting from a project preselects it. Submission returns a stable run ID. |
| F03 | Runtime and model capability inventory, Configurations | Avoids selections that look available but cannot execute. | Detect installed CLI/version separately from authentication and model access. Populate supported model/effort/tool controls from verified runtime capabilities. Show unavailable or unknown capability explicitly. |
| F04 | Versioned orchestrator and role presets, Configurations | Lets different parts of kelvin-implement use different models. | Each role can inherit or override runtime/model/effort. Show resolved values and their source. Presets preserve the existing skill defaults. Unsupported assignments fail before dispatch. |
| F05 | Actual cross-runtime role dispatch, runner | Makes model choices operational. | A Codex role starts a registered Codex worker, and a Claude role starts a registered Claude worker. Parent/run/task linkage and actual model identity are captured. Run-scoped overrides are explicit to the skill and dispatcher. |
| F06 | Immutable run configuration and context record, Run | Explains exactly what was launched. | Record prompt, preset version, resolved roles, requested and observed models/effort, skill hash, CLI version, repository revision, worktree, limits, and source references. Later preset edits do not rewrite the run. |
| F07 | Durable queue and worker ownership, runner | Work survives browser navigation and HTTP restarts. | Persist before dispatch, deduplicate submissions, track process/session ownership, and reconcile after restart. Never silently launch an extra worker for an unresolved attempt. |
| F08 | Stable tasks, dependencies, and agent attempts, Run | Separates project milestones from parallel work. | Tasks have IDs, acceptance criteria, dependencies, owners, and attempt histories. Dispatch only ready tasks. Retrying preserves previous outcomes. The project retains its existing fixed workflow stations. |
| F09 | Live orchestrator summary and agent inspector, Run | Answers who is doing what now. | Show current observable action, progress summary, next step, role, model, task, worktree, last activity, and explicit state. Selecting a task scopes its agent detail and output. |
| F10 | Ordered, replayable event capture, Run | Gives a trustworthy activity history and reconnect behavior. | Store event IDs, timestamps, source, parent/run/task/attempt links, and normalized event kind. Reconnect resumes from the last event. Preserve raw source events where needed for diagnosis. |
| F11 | Decision checkpoints and exact approval scope, Run and Projects | Supports kelvin-implement's go/no-go without losing context. | Show verified evidence, reviewed package, proposed next action, and required decision. Record feedback or approval against that package/version. Repeated clicks are idempotent. A preset cannot authorize later work. |
| F12 | Cancellation, interruption, and recovery, Run | Makes long-running work manageable. | Cancel all registered children and retain evidence/worktrees. Distinguish cancel requested from confirmed. Show orphaned/interrupted sessions and last confirmed state. Only expose pause/resume when semantics are supported. |
| F13 | Worktree ownership and artifact provenance, Project and Run | Keeps parallel changes attributable and isolated. | Record which task owns each worktree, revision, diff, test report, and PR. Preserve the skill's cleanup guards. Detect competing writes to the same worktree. |
| F14 | Usage accounting with coverage and provenance, Run and Metrics | Makes token burn credible. | Track provider-specific input/output/cache counters, deduplicate cumulative reports, and avoid parent/child double counting. Missing data is Unknown. Show partial coverage and estimated/reported cost separately. |
| F15 | Core metrics and drilldown, Metrics | Gives useful comparisons across projects and configurations. | Filter by project, run, role, phase, model, preset version, and date. Show success/failure/cancel counts, active versus waiting time, retries, tokens, and cost when available. Every aggregate links to contributing runs. |

Dependencies: F03 and F04 establish dispatch contracts for F05. F06 through F10 establish the records used by F11 through F15. Build execution and accounting behavior through the same orchestration interface used by the pages.

## P1: make daily operation easier

| ID | Feature and location | Why useful | Acceptance criteria |
| --- | --- | --- | --- |
| F16 | Command menu and keyboard navigation, workspace | Reduces repeated navigation as the number of projects grows. | Search pages, projects, runs, and actions. Provide a visible trigger and a scoped shortcut. Escape restores focus. All actions remain available through ordinary controls. |
| F17 | Local drafts, saved filters, and shareable local routes | Preserves working context. | Navigation and live updates preserve prompt/role drafts. Restore named filters after reload. URLs identify a project/run/task without depending on in-memory state. Clearly show unsaved configuration changes. |
| F18 | Needs-you queue, Projects and Runs | Collects decisions that otherwise disappear into logs. | Aggregate approval/clarification requests, failed checks, stale workers, and ready-to-review evidence. Each item has a reason, owner, age, and deep link. Resolve items when the underlying state changes. |
| F19 | Guidance and interrupt-and-redirect, Run | Lets the user steer work without starting over. | Distinguish normal guidance from interrupt requests. Show queued, delivered, acknowledged, or rejected status. Record the affected run/attempt. Disable unsupported controls with an explanation. |
| F20 | Task dependency and execution timeline views, Run | Makes parallel work and bottlenecks legible. | Switch between task list, dependency view, and time lanes using the same task records. Show blocked edges and overlapping work accurately. Provide an accessible text equivalent. |
| F21 | Inspectable context manifest and handoff packet, Run and agent inspector | Explains what an agent was given and what it produced. | Show prompt, skill/version, source files or references, allowed tools, inherited instructions, scope, and handoff artifacts. Distinguish actual captured context from a summary. Never include secrets. |
| F22 | Review workspace for diffs, tests, and findings, Run | Connects agent activity to evidence of quality. | Open artifacts beside the relevant task. Link findings to code/evidence and the orchestrator's fix-or-decline decision. Preserve reviewer independence and prior review passes. |
| F23 | Configuration diff and duplicate-from-run, Configurations | Makes tuning reproducible. | Compare role/model/effort/tool/limit changes between versions. Create a new preset or run from a snapshot. Show changes before launch; retain the original snapshot. |
| F24 | Budget controls and threshold notifications, Run and Configurations | Gives visibility into consumption and stop conditions. | Support role/run limits where enforceable. Distinguish estimated threshold alerts from hard limits. State accounting delay and cancellation semantics. Local notices require no external messaging. |
| F25 | Failure diagnosis and freshness, Run | Helps distinguish slow work from broken execution. | Show heartbeat freshness, process exit, rate-limit backoff, permission wait, dependency wait, and disconnected telemetry separately. A silent worker is not automatically classified as failed. |
| F26 | Session resume and deliberate branching, Run | Reuses useful context and supports alternative approaches. | Label resume, fork conversation, retry task, and create isolated worktree as distinct operations. Show what state and files are preserved. Expose only supported runtime operations. |
| F27 | Activity and artifact export, Run and Project | Makes work portable and reviewable outside the app. | Export a redacted JSONL event stream and a readable Markdown summary with decisions, configuration, artifacts, and provenance. Exporting does not silently publish or send it anywhere. |
| F28 | Accessible density, light/dark themes, and responsive layout | Keeps a dense dashboard comfortable to use. | Offer readable compact and comfortable layouts. Use semantic controls, visible focus, labels beyond color, reduced-motion behavior, and touch-sized targets. Stack inspectors on narrow screens without losing actions. |

Dependencies: F18, F19, F20, F22, and F25 rely on durable events and task identities. F23 and F26 rely on captured configuration/context. F24 relies on usage coverage and defined runner controls.

## P2: measure before expanding

| ID | Feature and location | Why useful | Acceptance criteria |
| --- | --- | --- | --- |
| F29 | Outcome-aware configuration comparison, Metrics | Helps choose models on observed results. | Compare similar workflow/task groups and show completion, review rework, retries, tokens, and active time together. Display sample sizes and missing data. Avoid a universal model score. |
| F30 | Repeated-work and usage anomaly detection, Metrics and Run | Surfaces loops and surprising token consumption. | Explain which measured baseline or repeated event triggered an alert. Keep suggestions inspectable and dismissible. Do not silently stop or reroute work without a configured policy. |
| F31 | Context/cache efficiency and handoff analysis, Metrics | Reveals redundant reads, repeated context, and expensive handoffs. | Use actual context/cache telemetry. Attribute a finding to a role/task/run and label uncertain inference. Separate cache savings from claimed billing savings. |
| F32 | Concurrency planning and queue fairness, Configurations and Runs | Keeps several projects from crowding each other out. | Enforce global and per-project worker limits. Explain queue order and dependency readiness. Display changes to scheduling policy before they affect queued work. |
| F33 | Replay a past run's timeline, Run | Supports investigation and learning from successful runs. | Scrub recorded events to reconstruct state at a timestamp. Clearly identify replay mode. Replay cannot execute historical commands or repeat external side effects. |
| F34 | Suggested next actions, Project and Run | Turns evidence into useful next steps. | Suggestions cite concrete project/run evidence and explain their expected effect. They remain proposals until invoked and do not alter permissions or configuration silently. |

## Roles to make configurable

The initial role library should mirror responsibilities in kelvin-implement:

- Orchestrator: plan, delegation, dependencies, synthesis, and decisions.
- Researcher / POC builder: code exploration, initial proof, and concrete diff.
- Spec and ticket planner: acceptance criteria and implementation slices.
- Implementer: one ready ticket in an isolated worktree.
- Verifier: targeted checks, live verification, regression, and evidence.
- Reviewer: standards/spec review and local review-bot checks.
- Independent adjudicator: read-only second opinion on plans and findings.
- PR / fix author: PR preparation and fixes already decided by the orchestrator.

Role slots do not mean a fixed number of agents. Create attempts when tasks require them. Keep POC, Verify, Spec & Tickets, Implement, Converge, Regression, Ship, and Cleanup as phases.

## Current preview coverage

The visual proposal demonstrates:

- Persistent sidebar and shared navigation.
- Quick navigation with a command menu.
- Active run summary, task selection, agent inspector, and context tabs.
- Guidance recorded in the sample activity feed.
- Project-scoped prompt composer and role/effort overrides.
- Immutable in-memory snapshots for queued preview runs.
- Approval or requested changes updating sample run and project state.
- Metrics filters using clearly labeled sample data.
- Two accent directions, density controls, and responsive light/dark styling.

Preview limits: there is no real worker, authentication/model discovery, durable queue, live token collection, guidance delivery, or external action. Reloading the preview resets sample records. Existing project pages are represented rather than embedded.

## Current primary-source evidence

These sources were checked on September 4, 2026. They support capability and interaction decisions; the particular navigation, styling, and priorities above are design recommendations.

1. Linear distinguishes active, awaiting-input, error, complete, and stale agent sessions. This supports explicit state and freshness indicators, plus an attention queue. [Agent interaction](https://linear.app/developers/agent-interaction), [best practices](https://linear.app/developers/agent-best-practices).
2. Claude's Agent SDK documents configurable subagents and parent-child attribution. This supports role-specific dispatch and event linkage where the installed runtime exposes those capabilities. [Subagents](https://code.claude.com/docs/en/agent-sdk/subagents).
3. Streaming input and approval callbacks support interaction during execution. Guidance, interruption, and permissions need separate states and runtime-specific adapters. [Streaming input](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode), [approvals and user input](https://code.claude.com/docs/en/agent-sdk/user-input).
4. Durable execution requires preserving enough history/state to recover progress. For this local app, the design uses SQLite and a supervised worker; it does not require adopting Temporal. [Temporal workflow execution](https://docs.temporal.io/workflow-execution).
5. Session resume/fork preserves conversation context and does not itself snapshot repository files. Keep conversation branching distinct from worktree creation. [Claude sessions](https://code.claude.com/docs/en/agent-sdk/sessions).
6. Claude's documented cost fields are estimates. Its top-level usage and model-level usage have different subagent inclusion rules. Adapter-level normalization and provenance are essential before aggregation. [Cost tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking).
7. WCAG 2.2 addresses focus visibility and target size. Keyboard access and usable controls remain requirements for dense operational interfaces. [Focus not obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum), [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum).

## Decisions to preserve during implementation

- Project Markdown remains the source of truth for human-facing project summaries.
- Runtime/task/agent records use separate durable storage with stable IDs.
- UI controls must correspond to real runner capabilities.
- Different providers can have different model, effort, tool, resume, and telemetry semantics.
- Visibility covers observable actions, evidence, and concise progress, not hidden reasoning.
- Presets configure execution but do not bypass the workflow's authorization gates.
- Unknown measurements remain unknown; estimated cost is not a claim about the user's bill.
- Do not expand the navigation with a standalone page for every new feature. Prefer a contextual inspector, tab, or filtered view when the owning entity already has a page.
