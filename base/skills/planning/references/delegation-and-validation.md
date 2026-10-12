# Delegating the preparation and independent validation

## Preparing the plan

After the goal and scope are clear, use subagents. Fit their number to the scope, risk, dependencies
and the available slots; the roles may be combined or run sequentially:

- **Product and scenarios:** writes the PRD from the confirmed requirements, the edge situations and
  the acceptance criteria. Passes missing business rules on as questions, does not invent answers.
- **Technical design:** explores the relevant code, proposes the architecture, data, contracts and
  integrations. For a larger feature the areas may be split with clear ownership.
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
subagents that did not write the plan. Give them the assignment, the confirmed decisions, the whole plan
and access to the relevant code and rules. Do not limit them to confirming the authors' conclusions.

- **One validator:** a smaller plan; it checks both product completeness and technical links.
- **Two validators:** a larger or riskier plan. The first focuses on the evidenced scope, business
  rules, scenarios and coverage of criteria; the second on feasibility, contracts, dependencies, data,
  testing and deployment. Both may report problems outside their main focus.

They check in particular:

1. Whether all business behavior has a confirmed source and the plan includes no unapproved extensions.
2. Whether the scenarios, the PRD, the technical chapters and the tasks describe the same result.
3. Whether the design matches the real code and the project rules; links and assumptions are true.
4. Missing steps, duplicates, contradictions, unclear contracts and the order of implementation.
5. Whether the tasks can be realized in the given order and concurrent tasks do not collide.
6. Coverage of the criteria by implementation and tests, feasible verification and clear completion conditions.
7. Relevant migrations, compatibility, deployment, recovery, security and performance.
8. The [task size](artifacts.md#task-size) and the justification of `complexity` and `risk`. The values
   select the implementer's model, so an unjustified `low` on a task touching permissions, billing,
   limits, data lifecycle or concurrency is a finding. The confirmed values go into the validation
   record of `progress.json`.

A finding contains an ID, severity/blocking impact, the place in the plan, an explanation and evidence
from the assignment, code or rules, the affected criteria/tasks, the proposed fix and any question for
the user. Validators do not rewrite the design, do not implement and do not run application check tools.

## Incorporation and finishing

The orchestrator merges duplicates, evaluates the findings and records their resolution in the progress.
It incorporates justified technical fixes; a rejection is evidenced with a reason. Business questions
go to the user via the question tool. Dependent parts wait for the answer, independent ones may continue.
Reflect the answers in the PRD, decisions, chapters, tasks and the briefs of the affected agents.

After fixes have the findings and the changed links re-checked in a targeted way by a new validator run
with the findings, the fixes and the changed parts, per
[one assignment per run](../shared/delegation.md#one-assignment-per-run). Repeat
the whole pass only for a change that affected the overall concept. Do not stop merely because a number
of iterations was reached; when depending on the user, state the open questions and the status
`awaiting_decision`. `ready` requires a consistent plan, finished independent validation and resolved
blocking findings.

If subagents are unavailable, prepare the available part yourself per
[delegation](../shared/delegation.md) and state explicitly that the independent
validation did not happen; do not switch the plan to `ready`.
