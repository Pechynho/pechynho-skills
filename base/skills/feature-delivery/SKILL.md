---
name: feature-delivery
description: Orchestrates delivery of the first verified version of a feature from an existing or new plan through programming, Playwright and code review including fixes, with saved progress and local checkpoint commits for takeover by another agent. Use only on an explicit request for this whole workflow.
---

# Feature delivery

Take a confirmed assignment to a first verified version ready for the user to try. The main agent is
the orchestrator: it holds the goal, the decisions, the dependencies, the integration and the resumable
state of the work. Run each phase per its skill; do not copy their procedures into a parallel workflow
of your own.

## Permissions and boundaries

An explicit assignment of this whole workflow authorizes planning, implementation, delegation per the
follow-up skills, dev click-through, code review, incorporation of evidenced findings in the confirmed
scope and ongoing local commits of this work. The orchestrator passes this context to the follow-up
skills; they do not repeat the question whether to present or fix findings. A user restriction takes
precedence. Merely loading the skill, recommending it or asking to edit it does not activate these
permissions.

Push, publishing, deploy, history changes and package installation need their own separate permission
per the [ground rules](shared/ground-rules.md#git-and-package-installation). Including a library in the design or in this
workflow is not consent to install it.

**Never invent business behavior.** It comes from the user or from already confirmed decisions. Raise
new rules, conflicts and scope extensions per the
[business questions procedure](shared/business-questions.md); dependent work
waits for a real answer, independent work continues. Make technical choices yourself only within the
confirmed behavior.

## 1. Takeover or resume

Load the assignment, plan, decisions, tasks, progress, the current branch, HEAD and the working tree
state. Follow [checkpoints and takeover](references/continuity.md). Verify the actual files and
evidence; a `done` status or a previous agent's message alone does not replace verifying the
dependencies. Keep others' work in progress. Do not reset, stash or clean the working tree automatically.

Determine the exact scope of the feature, a suitable working branch and a fixed base commit for the
final review. If the feature already contains an implementation, do not set the base to today's HEAD:
include its earlier commits and the relevant uncommitted changes. Clarify an unclear base branch or
scope with the user. Record the base once and do not move it with every checkpoint.

If the plan is missing, use [planning](../planning/SKILL.md). Judge an existing plan against the
current assignment and code; add missing decisions or outdated parts via planning. Do not recreate a
valid plan and do not repeat a successful validation without a change. Do not turn open questions into
your own assumptions. Use one plan progress per the [planning format](../planning/references/artifacts.md).

## Ongoing user feedback

Process feedback in any phase, including implementation, testing and fine-tuning after handover, via
[feature-feedback](../feature-feedback/SKILL.md). First record every request in the single
`feedback.md` next to the plan with a stable ID and status; load it also when resuming. A chat reply
alone does not replace recording the resolution.

Feedback determines the impact on the plan, a targeted update via planning if needed, and the
implementation via programming. In the progress update the affected tasks and the validity of checks;
keep the status of the individual FB only in the feedback file. Clearly assigned changes need no
repeated approval; do not implement unconfirmed proposals or unclear business behavior automatically.

After a new assigned change to an already handed-over or accepted version, set `delivery.status` back
to `in_progress` and the phase per the needed work; with a missing decision or environment use the
corresponding waiting or blocked status. Keep the earlier acceptance as history. Reopen only the
affected tasks and verifications, do not change the fixed review base and do not rerun the whole cycle
without reason. For a later standalone fix respect its scope and the original permission limits.

## 2. Implementation

Use [programming](../programming/SKILL.md), proceeding in coherent parts by task dependencies. Pass
the confirmed contracts, rules, file ownership and completion conditions including tests. Programming
decides the size of delegation and the models; the orchestrator need not write all the code itself.

The main agent integrates the results and runs the checks per the ground rules, grouped at the
end of a larger part and of the whole implementation; record skipped or failed checks explicitly.
After significant milestones update the progress and create a local commit per the continuity reference.
At the end of the phase offer the user a fresh session per its
[phase boundary rule](references/continuity.md#when-to-save-and-commit).

## 3. Functional and visual click-through

Use [playwright-testing](../playwright-testing/SKILL.md) in fix mode. Pass the relevant PRD scenarios,
the whole feature scope, the revision and the confirmed decisions; testers may be explicitly assigned
to derive the scenarios. The Playwright skill decides the number of testers; do not add verifiers.

Verify the real dev environment and that the running application matches the tested code. Have
evidenced problems fixed via programming and the affected scenarios and their links repeated in a
targeted way. Do not make unapproved product or visual extensions under the guise of a fix. If the
feature has no browser-verifiable scenario, record the concrete reason for non-applicability and the
corresponding other verification. An unavailable browser or dev server is a blockage, not
non-applicability.

## 4. Code review and fixes

After the click-through and its fixes run [code-review](../code-review/SKILL.md) in fix mode. The
scope covers the whole feature from the recorded base to the current revision including relevant
staged, unstaged and new files; it must not shrink to the last commit or the last fix. When unrelated
changes are mixed in, pass an exact scope map with exclusions and reasons.

Follow the reviewers, the verification and the synthesis prescribed by the review skill. Have
confirmed problems fixed via programming and resolve business questions with the user. Only record
optional recommendations outside the scope. Confirmed existing problems outside the feature are fixed
only with the user's consent per the review skill; the whole-workflow assignment does not cover them. Link fixes to the original finding IDs and their follow-up
verification.

After a fix rerun the checks whose results the change may have invalidated: relevant tests,
click-through or a targeted review. A UI change after the review may therefore mean returning to
Playwright. Do not repeat the whole cycle without reason. Every fix needs verification matching its
impact; on repeated failures find the cause and update the plan instead of blind repetition. After the
review and its fixes save a checkpoint and offer the user a fresh session per the
[phase boundary rule](references/continuity.md#when-to-save-and-commit).

## 5. Handover of the first version

Handing over a ready version requires met acceptance criteria, the relevant checks, browser coverage
(or evidenced non-applicability), a finished review and resolved blocking findings. Do not present a
missing environment, decision or an unverified fix as a completed pass. On a blockage record the state
and the next step, and present the achieved result as partial.

Also check all items of `feedback.md`: requests included in the handed-over version must be verified.
Postponed or superseded points need an evidenced reason and, where applicable, the user's decision;
open points must not disappear from the handover. Feedback cannot be bypassed by marking the version
ready or by postponing it arbitrarily.

Save the final progress and a local checkpoint. Hand over to the user:

- what the first version contains and what was deliberately postponed;
- where to open it and brief steps to try it, including roles and dev data, without revealing secrets;
- the checks actually performed and the results of the click-through and the review;
- limitations, remaining non-blocking findings and any decision needed;
- the path to the plan/progress, the branch, the last commit and any uncommitted changes;
- the path to the feedback record, the resolved IDs and the remaining points with their status and reason.

Mark the version `ready_for_user`, not automatically accepted by the user; acceptance is recorded only
from an explicit reply. The autonomous pass ends with the handover; further work follows new user
instructions, do not start further extensions or new whole review cycles on your own.
