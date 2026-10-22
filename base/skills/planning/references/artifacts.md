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
├── mockups/
│   ├── index.json
│   └── 01-member-list.html
├── progress.json
└── log.jsonl
```

The chapters are examples, not mandatory areas of every change. A small plan may have a single chapter
and task file; do not create empty documents. Reorganize an existing plan only per the assignment.
Paths inside JSON are relative to the plan folder, paths to source code to the project root; Markdown
links are relative to the document that contains them.

The plan is versioned and must work for another developer who has only the repository. Everything a
plan document, the tasklist, the progress or the log relies on is versioned too: its chapters,
mockups, feedback and the source code. The
[work directory](../shared/project-context.md#work-directory), temporary files, a published artifact,
a local tool state or the conversation may accompany a versioned copy or summary, never replace it.
Move what the plan needs into its folder and write the substantial conclusions of working material
into the plan, the progress or the log.

Read and change the tasklist, the progress and the log with the [plan tool](../shared/plan-tool.md)
where it is available; it implements the rules below.

With user feedback the folder may also contain `feedback.md` per
[feature-feedback](../../feature-feedback/SKILL.md), linked from the README. It records the requests
and their resolution with stable FB IDs; the status of implementation tasks still belongs only in
`progress.json`. When revising the plan, keep the links of FB to decisions, criteria and tasks.

## Content of the Markdown documents

- **README.md:** a short goal and scope, an overview of stages and links to the PRD, decisions, all
  chapters, the JSON index, the progress and any mockups. Do not duplicate the status and task counts
  by hand.
- **mockups/*.html:** the mockups per the [mockups procedure](../shared/mockups.md), listed in the
  [mockup index](#mockup-index); the approved ones bind the look of the implementation.
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
| `references` | Paths to chapters, optionally with a Markdown anchor, and to approved mockups; inside the plan folder. |
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

## Mockup index

`mockups/index.json` exists whenever the plan has mockups or a recorded refusal of them. It contains
`schema_version`, `mockups` and `declined`:

```json
{
  "schema_version": 1,
  "mockups": [
    {"id": "M-001", "file": "01-member-list.html", "screens": "Member list", "status": "approved",
     "decision": "D-004", "acceptance_criteria": ["AC-002"], "preview": "https://…"}
  ],
  "declined": [{"scope": "Invitation e-mail", "decision": "D-005"}]
}
```

Each mockup has a unique `id`, a `file` relative to the `mockups/` folder, the `screens` it shows and a
`status`: `proposed` while the user has not approved it, `approved` with the `decision` that records the
approval. `acceptance_criteria` and `preview`, a published link, are optional; the preview never
replaces the file. `declined` lists the visual scope the user did not want mockups for, each with its
decision. Rejected variants do not appear. A re-approved mockup keeps its ID and file and gets the new
decision; Git keeps the previous version.

`plan.py validate` checks that the index and the files in `mockups/` match, that approvals and
refusals name a decision present in `decisions.md`, that tasks reference only approved mockups and that
the README links the mockups.

## Single source of progress

The state of realization lives in two files: `progress.json` holds the current state needed to decide
the next step, `log.jsonl` holds the history that justifies it. Keep `progress.json` small; anything
that only accumulates goes into the log.

`progress.json` contains:

- `schema_version`, `feature`, `updated_at`;
- `plan_status`: `draft`, `awaiting_decision`, `validating` or `ready`;
- `implementation_status`: `not_started`, `in_progress`, `blocked` or `done`;
- `tasks`: a map by task ID with `status`, `owner`, `blockers` and `updated_at`;
- `open_questions`: IDs of open questions from `decisions.md`;
- `handoff`: the current context, work in progress and the next step;
- in `feature-delivery` also `delivery` per the
  [continuity rules](../../feature-delivery/references/continuity.md).

`log.jsonl` is append-only, one JSON object per line, each with `at` (UTC timestamp) and `type`:

| `type` | Required fields | Records |
|---|---|---|
| `task` | `id`, `status` | A status change with `from`, and `evidence` for `done` or `reason` for `cancelled`. |
| `check` | `subject`, `result` | A check actually performed: the command or scenario, scope, `revision`, a link to the evidence. |
| `finding` | `id`, `status` | A finding from validation, testing or review: `source`, `severity`, `summary`, affected `tasks`, `fix`, `evidence`. Status `open`, `resolved`, `rejected` or `awaiting_decision`. |
| `validation_plan` | `pass`, `mode`, `cells` | The cells of one validation pass per the [validation mode](delegation-and-validation.md#validation-mode): `mode` `single`, `focus`, `areas` or `recheck`; each cell has an `id`, a `focus`, its `chapters` and `tasks`, and `integration: true` for the cell over the links between areas. |
| `validation` | `validators`, `result` | One validator run: `pass` and `cell`, `coverage` `covered` or `partial` with `unchecked`, scope, revision and the tasks whose `complexity` and `risk` it confirmed (`confirmed_tasks`). |
| `checkpoint` | `commit` | A checkpoint commit and the milestone it saves. |
| `note` | `text` | Any other fact a later session needs, for example the reason of a decision about the work. |

Never rewrite or delete log lines. A later `finding` record with the same `id` updates the earlier
one field by field; the current state of a finding is the merge of its records in order. Do not
copy log content back into `progress.json`.

Task statuses: `pending`, `in_progress`, `blocked`, `done`, `cancelled`. When the plan is created, the
tasks are `pending`, the owner `null` and the log empty. When editing an existing plan, keep the real
status and the evidenced history. `done` needs evidence of the `done_when` conditions and the
verification, finished subtasks and done dependencies. Cancelling a task requires a reason and a check
of the impact on its consumers and on the coverage of criteria; cancelled work is not finished work.

Do not store statuses in the tasklist as well, nor by hand in a `progress.md`. Derive counts and
percentages from the items, without counting parents and subtasks twice. Generate any human-readable
overview from the JSON. The main orchestrator updates the progress at a milestone, status change,
blockage and handover of work; subagents supply the inputs and do not write concurrently into the
progress or the log.

The status `implementation_status: done` does not mean a finished click-through/review or acceptance
by the user.
