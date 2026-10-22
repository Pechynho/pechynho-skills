# Delegating the preparation and independent validation

## Preparing the plan

After the goal and scope are clear, use subagents. Their number follows the
[number of runs](../shared/delegation.md#number-of-runs): each role below once, or once per area when
the role does not fit one run; roles that share context may be combined, and runs are sequenced by
their contracts:

- **Product and scenarios:** writes the PRD from the confirmed requirements, the edge situations and
  the acceptance criteria. Passes missing business rules on as questions, does not invent answers.
- **Technical design:** explores the relevant code, proposes the architecture, data, contracts and
  integrations. For a larger feature one run per area, each owning its chapter; the contracts between
  the areas are agreed first and owned by the main agent.
- **Realization and verification:** from the linked PRD and technical design builds the tasks,
  dependencies, testing and deployment, sized per [task size](artifacts.md#task-size). The final
  tasklist must not run ahead of unifying the contracts.

The main agent owns the shared assignment, the decisions, the integration and the progress. Give each
agent its output files, scope, verified facts and their sources, the confirmed decisions, the open
questions, the concrete project rule files, the contracts and information about concurrent work.
Explicitly forbid inventing business behavior and doing the implementation. A subagent returns a
proposal, sources, ambiguities and risks. It directs questions to the main agent; only the main agent
unifies the questions and asks the user.

Model choice follows [delegation](../shared/delegation.md): the stronger model
for a complex design and for validation, the weaker one with a precise brief for clearly bounded
processing of a confirmed assignment.

## Validating the finished design

Launch the validators only over the linked version of the documents and the tasklist. Use new
subagents that did not write the plan. Give them the assignment, the confirmed decisions, their part
of the plan and access to the relevant code and rules. Do not limit them to confirming the authors'
conclusions.

### Validation mode

Choose the mode by whether one validator can check the whole plan against the code in one run per
[one assignment per run](../shared/delegation.md#one-assignment-per-run), not by the number of tasks
alone; the risk raises the mode, never lowers it.

| Mode | When | Cells |
|---|---|---|
| `single` | A small plan: one area, a few tasks, no risky contract. | One validator checks both product completeness and technical links. |
| `focus` | A medium or riskier plan that one validator still reads whole. | Two validators. The first focuses on the evidenced scope, business rules, scenarios and coverage of criteria; the second on feasibility, contracts, dependencies, data, testing and deployment. Both may report problems outside their main focus. |
| `areas` | A large plan: its areas and their code do not fit one run. | One validator per area checks inside its area the match with the code and rules, gaps and contradictions, the order and collisions of tasks, the coverage by tests, the migrations and deployment, and the task size with `complexity` and `risk`. One integration validator after them checks over the whole plan the business sources and that the PRD, chapters and tasks describe the same result, and across the areas the contracts, the order and collisions of tasks and the coverage of criteria. |
| `recheck` | After fixes of validation findings. | Cells only for the affected areas, and the integration cell when a contract between areas changed; see [incorporation](#incorporation-and-finishing). |

In the `areas` mode write a short **plan map** first, `{work_dir}/planning/{feature}/validation-map.md` next to the notes per
[work directory](../shared/project-context.md#work-directory): the areas with their
chapters and tasks, the contracts between them and which tasks consume them. Every area validator
gets the README, the PRD, the decisions and the map plus the chapters, tasks and code of its own area;
it reads another area only where a contract needs it. The integration validator gets the whole plan,
the map and the summaries of the area validators and reads code only for a link. Small areas may share
one validator run; a risky area (permissions, billing, data lifecycle, migrations, concurrency) keeps
its own.

Record the cells before launching, with the IDs of the tasks and the chapters of each area:

```bash
plan.py {plans_dir}/{feature} log validation_plan pass=V1 mode=areas cells='[{"id":"A1","focus":"data and migration","chapters":["chapters/01-data.md"],"tasks":["T-001","T-002"]},{"id":"INT","focus":"integration","integration":true}]'
```

When a validator returns, record its cell with `plan.py log validation pass=V1 cell=A1
validators='["V-A1"]' result=… coverage=covered`, or `coverage=partial unchecked='[…]'` with what it
could not check; `plan.py validations` then shows the cells still to brief, and the integration cell
once the area cells are covered. A partial cell is finished **in the same pass**: brief a new run for
its unchecked part only and record it with the same `pass` and `cell`; its last record counts. A cell
lost to an interruption has no record and is briefed again whole. A later pass never closes a cell
of an earlier one.
Without the plan tool keep the same records by hand.

The validators check in particular:

1. Whether all business behavior has a confirmed source and the plan includes no unapproved extensions.
2. Whether the scenarios, the PRD, the technical chapters and the tasks describe the same result.
3. Whether the design matches the real code and the project rules; links and assumptions are true.
4. Missing steps, duplicates, contradictions, unclear contracts and the order of implementation.
5. Whether the tasks can be realized in the given order and concurrent tasks do not collide.
6. Coverage of the criteria by implementation and tests, feasible verification and clear completion conditions.
7. Relevant migrations, compatibility, deployment, recovery, security and performance.
8. The [task size](artifacts.md#task-size) and the justification of `complexity` and `risk`. The values
   select the implementer's model, so an unjustified `low` on a task touching permissions, billing,
   limits, data lifecycle or concurrency is a finding. The confirmed values go into the
   `confirmed_tasks` of the cell's `validation` record in the plan log.

A finding contains an ID, severity/blocking impact, the place in the plan, an explanation and evidence
from the assignment, code or rules, the affected criteria/tasks, the proposed fix and any question for
the user. Validators do not rewrite the design, do not implement and do not run application check tools.

## Incorporation and finishing

The orchestrator merges duplicates, evaluates the findings and records them and their resolution as
`finding` records in the plan log.
It incorporates justified technical fixes; a rejection is evidenced with a reason. Business questions
go to the user via the question tool. Dependent parts wait for the answer, independent ones may continue.
Reflect the answers in the PRD, decisions, chapters, tasks and the briefs of the affected agents.

After fixes have the findings and the changed links re-checked in a targeted way by a new validator run
with the findings, the fixes and the changed parts, per
[one assignment per run](../shared/delegation.md#one-assignment-per-run): a new pass in the `recheck`
mode with cells only for the affected areas, and the integration cell when a contract between areas
changed. Repeat the whole pass only for a change that affected the overall concept. Do not stop
merely because a number of iterations was reached; when depending on the user, state the open
questions and the status `awaiting_decision`. `ready` requires a consistent plan, finished independent
validation with every cell of all its passes covered (`plan.py validations --open`), and resolved
blocking findings.

If subagents are unavailable, prepare the available part yourself per
[delegation](../shared/delegation.md) and state explicitly that the independent
validation did not happen; do not switch the plan to `ready`.
