# Plan documents and the record of realization

## Structure

```text
{plans_dir}/{feature}/
├── README.md
├── prd.md
├── decisions.md
├── chapters/
│   ├── 01-data-and-domain.md
│   ├── 02-backend.md
│   ├── 03-ui.md
│   └── 04-testing-and-rollout.md
├── tasks/
│   ├── index.json
│   ├── 01-data-and-domain.json
│   ├── 02-backend.json
│   ├── 03-ui.json
│   └── 04-testing-and-rollout.json
└── progress.json
```

The chapters are examples, not mandatory areas of every change. A small plan may have a single chapter
and task file; do not create empty documents. Reorganize an existing plan only per the assignment.
Paths inside JSON are relative to the plan folder, paths to source code to the project root; Markdown
links are relative to the document that contains them.

With user feedback the folder may also contain `feedback.md` per
[feature-feedback](../../feature-feedback/SKILL.md), linked from the README. It records the requests
and their resolution with stable FB IDs; the status of implementation tasks still belongs only in
`progress.json`. When revising the plan, keep the links of FB to decisions, criteria and tasks.

## Content of the Markdown documents

- **README.md:** a short goal and scope, an overview of stages and links to the PRD, decisions, all
  chapters, the JSON index and the progress. Do not duplicate the status and task counts by hand.
- **prd.md (Product Requirements Document):** for whom, why and what we build; scenarios, business
  rules, included and postponed scope, errors and exceptions, constraints and measurable or observable
  acceptance criteria with stable IDs `AC-001`. For rules state the source of the user decision.
  Concrete classes and database tables belong in the technical design.
- **decisions.md:** decisions `D-001`, their type (business/technical), status, source, reason,
  alternatives and impacts. Mark a business decision as confirmed only with an evidenced user
  assignment or a confirmed rule. Separate open questions `Q-001` from accepted decisions; state the
  blocked parts. Mark a superseded decision and link to the new one, do not delete its history.
- **chapters/*.md:** the current state with links to the code, the target solution, contracts, links
  and risks. As relevant cover data, migrations and backfill, concurrency, permissions, UI states,
  responsiveness, accessibility, translations, integrations, libraries, performance, diagnostics,
  testing and deployment including compatibility and rollback. Explain the substantial decisions;
  do not prescribe every line of code.

## JSON tasklist

`tasks/index.json` contains `schema_version`, `feature`, `task_files` (a list of relative paths) and
`phases` (phase ID, name, list of task IDs). The order of phases is recommended; the real dependencies
are determined by the tasks. Each task file has `schema_version` and a `tasks` array.

Each task or subtask has a globally unique stable ID, for example `T-001` and `T-001.1`:

| Field | Meaning |
|---|---|
| `id`, `title` | Identity and a short name of the result. |
| `parent_id` | ID of the parent task, or `null`; subtasks are separate items. |
| `outcome` | The unambiguous required result and the boundary of the work. |
| `references` | Paths to chapters, optionally with a Markdown anchor. |
| `acceptance_criteria` | IDs of the PRD criteria the task contributes to. |
| `depends_on` | IDs of tasks whose completion is required before the start. |
| `code_areas` | Verified existing and explicitly marked proposed paths/modules. |
| `implementation` | Concrete steps, contracts and necessary links. |
| `tests` | Tests written with the implementation; if unsuitable or the layer is not tested, an explanation. |
| `verification` | Checks and expected evidence; the main agent runs them at a suitable milestone. |
| `done_when` | Observable completion conditions. |
| `complexity`, `risk` | Low/medium/high with a short justification; they select the implementer's model, see [task size](#task-size). |
| `parallelization` | What can be worked on concurrently and the file ownership limits. |

A parent task groups subtasks; do not count its work again as further implementation. A parent task
is done only after all subtasks and its own integration conditions are met. A subtask does not depend
on the completion of its parent. Check cycles in dependencies and in the hierarchy. Every PRD criterion
must have a task and a way of verification; technical preparatory tasks may have empty
`acceptance_criteria` but must explain which other tasks they enable.

### Task size

A task or subtask is sized for one subagent run per
[one assignment per run](../shared/delegation.md#one-assignment-per-run): one
coherent result that an implementer finishes in roughly 80 tool calls, including its tests, without
needing results from the main agent in between. Signs of a task that is too big: it spans backend, UI
and translations of several screens, it touches more than a handful of modules, or its `implementation`
lists many independent steps. Split such a task into subtasks `T-001.1`, `T-001.2` with their own
`done_when` and order them with `depends_on`; the parent keeps the integration. Do not split below a
coherent result: a subtask that cannot be verified on its own is too small.

`complexity` and `risk` decide the implementer's model per
[delegation](../shared/delegation.md#model-by-task). Give them a real
justification, not a default value; a task that touches access, billing, limits, data lifecycle or
concurrency is not `low` risk. The validators confirm the values and the validation record in
`progress.json` states which tasks they confirmed.

## Single source of progress

`progress.json` contains:

- `schema_version`, `feature`, `updated_at`;
- `plan_status`: `draft`, `awaiting_decision`, `validating` or `ready`;
- `implementation_status`: `not_started`, `in_progress`, `blocked` or `done`;
- `tasks`: a map by task ID with `status`, `owner`, `blockers`, `evidence` and `updated_at`;
- `open_questions`: IDs of open questions from `decisions.md` and the blocked tasks;
- `validation`: validators, the scope/revision of their check, findings with stable IDs, their
  resolution (`open`, `resolved`, `rejected`, `awaiting_decision`), reasons and results of the re-check;
- `checks`: the checks actually performed, scope/revision, result and a link to the evidence;
- `handoff`: the current context, work in progress and the next step.

Task statuses: `pending`, `in_progress`, `blocked`, `done`, `cancelled`. When the plan is created, the
tasks are `pending`, the owner `null`, the check results empty. When editing an existing plan, keep the
real status and the evidenced history. Cancelling a task requires a reason and a check of the impact on
its consumers and on the coverage of criteria; cancelled work is not finished work.

Do not store statuses in the tasklist as well, nor by hand in a `progress.md`. Derive counts and
percentages from the items, without counting parents and subtasks twice. Generate any human-readable
overview from the JSON. The main orchestrator updates the progress at a milestone, status change,
blockage and handover of work; subagents supply the inputs and do not write concurrently into the
shared file.

In the whole `feature-delivery` workflow the same `progress.json` is extended with the delivery phase,
the fixed review base, checkpoints and a resumable handover per the
[continuity rules](../../feature-delivery/references/continuity.md). The status
`implementation_status: done` does not mean a finished click-through/review or acceptance by the user.
