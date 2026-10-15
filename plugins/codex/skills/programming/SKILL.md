---
name: programming
description: Implements features, changes and fixes, including verified code-review findings. Works alone or delegates by scope, difficulty and risk; coordinates models, tests, integration and the final verification.
---

# Programming

Before starting, resolve the [project context](shared/project-context.md) and follow the
[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.

Bring the assigned change to a working, verified implementation with matching tests. The main agent
owns the assignment, the split of work, the integration and the resulting quality, also when delegating.

Within [feature-delivery](../feature-delivery/SKILL.md) take the scope and permissions from the
orchestrator and report the status of tasks, fixes and checks into the single plan progress; local
checkpoints and the further phases are the orchestrator's. When taking over feedback via
[feature-feedback](../feature-feedback/SKILL.md), load the assigned FB IDs, expected results, decisions
and plan links; return the implementation and the verification evidence under the same IDs, and the
main agent updates `feedback.md`. Record new feedback found during this work the same way first.
Task status stays in the plan progress; do not copy it into the FB.

## 1. Clarify the result and the context

Find the required behavior, the affected parts, existing patterns and the test infrastructure.
Separate what follows from the assignment from what is still an open question.

**Never invent business behavior, neither the main agent nor subagents.** It must come from the user's
assignment or from rules and decisions already confirmed; existing code, a test or a plan draft does
not by itself replace a user decision. A choice that changes access, billing, limits, data lifecycle or
the outcome of a user scenario is a business decision even when it shows up as an implementation
detail. Raise such questions per the
[business questions procedure](shared/business-questions.md): collect them, implement everything
the answer does not change first and ask in one batch per its
[when to ask](shared/business-questions.md#when-to-ask) rule; only the dependent remainder waits and is
finished after the answer. Do not ask decided questions again.
Make technical choices yourself within the confirmed behavior.

When taking over a code review, load the synthesis, finding IDs, evidence, the reviewed revision, the
proposed solutions, the user's answers and the permitted fix scope. Check that the findings still hold in
the current code. Do not implement refuted findings or open business assumptions; include optional
improvements only when the assignment covers them. Do not ask again for consent already given.

When implementing a plan from [planning](../planning/SKILL.md), load its `README.md`, PRD, decisions
and relevant chapters; take the state, the ready tasks and the task details from the
[plan tool](shared/plan-tool.md) (`status`, `next`, `show`) instead of reading whole task files.
Respect the dependencies and the stable task IDs. The main agent updates the progress at milestones,
blockages and handover (`set`, `log check`); do not duplicate the status into the tasklist. `done` requires the task's conditions including the relevant verification.
A newly discovered business ambiguity goes to the user and the answer back into the plan.

## 2. Choose how to work

Judge scope, difficulty, risk and dependencies separately; the number of changed lines alone does not
pick the model. A short payment or permission change can be harder than a large mechanical edit.

- **Do a small, clear change yourself.** It saves context, time and the cost of handing over the assignment.
- **Split medium and larger work among subagents.** Delegate coherent results sized for one run,
  typically one plan task with its tests, not small individual steps and not several tasks at once.
  The main agent handles shared decisions and integration.
- Independent parts may run in parallel; order dependent tasks by their contracts and inputs. Fit the
  number of agents to the available slots and the truly parallelizable work.
- Adjust the split as you learn. A small fix may become a larger task; an unclear task may, after
  analysis, become a precisely bounded implementation for a weaker model.

For model choice, subagent briefs and the case of unavailable subagents read
[delegation](shared/delegation.md). State the split of larger work briefly. Pass context through
files, messages or both as needed.

## 3. Implement and integrate

Before parallel work assign file owners and agree the shared interfaces. Coordinate concurrent edits of
the same file explicitly; announce a change of a shared contract to all affected agents. Subagents do
not widen their scope on their own.

**Write tests together with the change**, per the
[ground rules](shared/ground-rules.md#implementation-and-tests-order) and the project's testing
rules. Tests verify behavior, boundaries and regressions;
they do not merely restate the implementation. A subagent may write the implementation and the tests,
but it does not run the checks; it hands the requests to the main agent, finishes the independent part
and ends with a handover. It does not wait for the result: the main agent runs the checks and hands the
fixes to the same agent within minutes of its handover or to a new run per
[one assignment per run](shared/delegation.md#one-assignment-per-run).

After taking over the results, the main agent reads the changes and checks the assignment, the rules
and the links between the parts; a subagent's result is not automatically correct. Resolve conflicts
before the final checks; do not overwrite others' work in progress. An additional model check may help
on a risky part, but run a separate multi-stage code review only when requested or justified for the task.

## 4. Verify at the right moment

Follow the [verification rules](shared/ground-rules.md#verification): only the main agent runs the
checks, grouped after the whole work or a larger coherent part, with the scope chosen by the change and
the mandatory project checks. Merge identical subagent requests; a failure goes with the failing cases
and the diff back to the subagent only within minutes of its handover, otherwise to a new short run,
per [one assignment per run](shared/delegation.md#one-assignment-per-run). On a concrete failure
verify the affected fix in a targeted way first. Do not repeat a successful run without
a new change, a failure or an unresolved risk.

If a formatter changes the code, review its diff and add follow-up verification by impact. Fix your own
errors. Describe and evidence an unrelated pre-existing failure instead of marking the whole suite as
passing. State a missing environment or a skipped check as a limitation.

## 5. Hand over the result

Done means integrated changes within the permitted scope, matching tests and the relevant checks
performed. Do not mistake an open dependency on a user answer for a finished implementation.

Summarize what changed, why, how it was verified and what remains open. Map fixes from a review to the
original finding IDs. Report the actual check results and the remaining limitations. Commit, push,
package installation and other actions with special project rules still need the corresponding
permission; delegation alone does not grant it.
