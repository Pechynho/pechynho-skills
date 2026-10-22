---
name: planning
description: "Prepares a feature implementation plan in the project's configured plans directory: code exploration, brainstorming, PRD, technical design and a JSON tasklist, independently validated by other subagents. Business questions are decided by the user. Use on a request to design, elaborate or write down a plan."
argument-hint: "<feature idea, or path to an existing plan>"
---

# Planning

Before starting, resolve the [project context](shared/project-context.md) and follow the
[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.

Take an idea to a clear goal, a confirmed scope and a feasible plan in `{plans_dir}/{feature}/`
(see [project context](shared/project-context.md#plans-directory)).
Planning by itself does not authorize implementation. If the user only wants brainstorming, stay with
exploration, questions and working notes; create the final documents only when asked.

Also read the closed product and technical decisions relevant to the feature. When editing an existing
plan, first load its structure and progress; do not rewrite the history of decisions, the task IDs or
the state of realization.

## 1. Find the intent and open working notes

From the assignment and the confirmed decisions find the target users, the problem, the expected
result, business rules, constraints and the expected scope. If the business model relevant to the
feature is missing, ask about it first. Do not re-analyze the whole application model for a local change.
While waiting, do the exploration that does not depend on the answer.

Keep running notes in `{work_dir}/planning/{feature}/notes.md` per
[project context](shared/project-context.md#work-directory). Never create this file inside published
content or versioned documentation. When resuming,
load it; update it after a significant finding, answer or scope change. Capture briefly:

- the goal, the current scope and the source of the assignment;
- confirmed decisions with ID, reason and a link to the source or an exact summary of the user's answer;
- open questions with ID and the parts of work they block;
- proposed, rejected and postponed options, separated from the confirmed requirements;
- findings from the code with paths, verified revision and working tree state;
- the current phase and the next step for resuming after a context cut.

The notes are not a transcript of the whole conversation. The final plan must be understandable on
its own without the temporary file; carry the confirmed conclusions into its documents.

## 2. Explore the code and brainstorm with the user

Find the real architecture, existing similar features, the data model, interfaces, permissions, the
test infrastructure and the integration points. Distinguish evidenced behavior from an unverified
assumption. Old plans and the current code are inputs for exploration, not an automatically valid
product specification.

Propose solution variants, reuse of existing code, a simpler first stage and possible extensions of the
application. For new features and libraries explain the benefit, cost, complexity and the alternative
using the current state. Before recommending a library, check its current primary documentation,
compatibility with the project, license and maintenance state. Do not install it during planning. Mark
an unverified option as unverified. Include an extension in the scope only after the user's decision;
store the others as postponed proposals.

**Never invent business behavior, not even through subagents.** A missing rule is not replaced by a
recommended variant, the current implementation, a test, common practice or the plan author's guess.
A choice affecting access, billing, limits, data lifecycle or the outcome of a user scenario belongs to
the user; decide technical details yourself within the confirmed behavior. Ask per the
[business questions procedure](shared/business-questions.md), do not repeat
resolved questions, and leave the dependent part open while continuing independent work.

End the brainstorming once the goal, the feature boundaries, the key scenarios and the acceptance
criteria are clear and the user has decided the questions needed for the design. Summarize the agreed
scope briefly; do not ask for repeated approval of confirmed points. Bring business questions discovered
later back to the user.

## 3. Prepare the plan with subagents

Read the [document and data structure](references/artifacts.md) and
[delegation and validation](references/delegation-and-validation.md). Cut the plan into **areas**: a
coherent part of the design with its chapters, code and tasks, for example the data model, an API, one
screen or a migration. A small plan is one area. Delegate the preparation by area per the
[number of runs](shared/delegation.md#number-of-runs). Pass the shared confirmed assignment, the
relevant decisions and the concrete rule files, the code findings and an explicit ban on adding
business decisions. Assign file owners and contracts between the areas; choose the way of passing
information yourself. The same areas carry on into the validation.

The main agent links the PRD with the technical chapters, resolves technical conflicts and only from a
consistent design has the implementation tasks with their dependencies built. A task includes its tests
according to the existing project infrastructure; do not plan writing them after the implementation is
approved. Mark an uncertainty requiring a technical experiment as a blocking exploration task with a
clear output; do not record an unverified result as an established technical fact.

## 4. Validate independently and fix

Hand the finished design automatically to validators, other subagents than the authors. The size of
the plan picks the [validation mode](references/delegation-and-validation.md#validation-mode): one
validator for a small plan, two by focus for a medium one, and for a large plan one validator per area
plus an integration validator over the links between areas. Record the validation cells with
`plan.py log validation_plan` so that an interrupted validation resumes from `plan.py validations`.
Validators check the plan against the assignment, the confirmed decisions and the real code. They
pass their findings to the main agent, who evaluates them and incorporates justified technical fixes.
Business questions go to the user and the answer is reflected in all affected parts. After changes,
have the fixed points and their links re-checked in a targeted way, only in the affected areas.

The main agent verifies JSON parsing, links, uniqueness of IDs, existence of dependencies, absence of
cycles and coverage of the acceptance criteria by tasks and verification, with `plan.py validate` of
the [plan tool](shared/plan-tool.md) where available; it creates the progress with `plan.py init`. For pure planning do not run
application tests, linters or builds. Do not mark the plan as ready while a necessary decision is
missing, a blocking finding is unresolved or the required independent validation could not be performed.
Record the limitations transparently.

## 5. Offer mockups of a visual result

When the feature changes something the user sees, offer mockups per the
[mockups procedure](shared/mockups.md) so the user can picture the result before the implementation;
skip this step otherwise. Number the screens by the PRD scenarios and criteria they show. Feedback that
changes behavior goes back into the plan and the affected parts are re-checked per
[validation](#4-validate-independently-and-fix). An approved mockup binds the look of the
implementation.

## 6. Hand over the result

Summarize the goal, the agreed scope, the documents, the stages, the validation result and any open
points. Store the output in `{plans_dir}/{feature}/`; the indexes must reach all chapters and tasks.
Write the true state of the plan into the progress; implementation tasks are not done by being planned.
Start the implementation via [programming](../programming/SKILL.md) only if the user assigned it.
Hand over the confirmed decisions, the task index, the progress, the dependencies and the limitations.
Leave a clear next step so that the next agent does not have to derive the state from the conversation.
