---
name: feature-feedback
description: Records user feedback on a feature with stable FB IDs and resolution status, maps its impact onto the existing plan and implements assigned changes via programming. Use during feature-delivery or alone when fine-tuning after testing or handover; a status question or brainstorming alone is not an instruction to implement.
argument-hint: "<feedback on the feature>"
---

# Feature feedback

Before starting, resolve the [project context](shared/project-context.md) and follow the
[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.

Keep the user's requests traceable from receipt to implementation and verification.

## Record

Use a single `feedback.md` in the folder of the feature's existing plan, usually
`{plans_dir}/{feature}/feedback.md`, and link it from the plan index. Create the file at the first
feedback item. Without a plan use the same path with a descriptive feature name; recording a small fix
alone does not require creating a PRD, a tasklist or the whole planning workflow. First search for an
existing record of the same feature; do not create a second one.

`feedback.md` is the source of requests and of the status of their resolution. `progress.json` remains
the single source of the status of implementation tasks and checks. Link them by IDs and links; do not
copy the tasklist or check logs into the record. The progress may contain the path to the record and the
IDs of the feedback currently handled; do not keep a second map of their statuses in it. The main agent
writes the record; subagents hand their results to it.

Record every separately assessable point of the user before the related implementation as `FB-001`,
`FB-002` etc. within the feature. Never renumber or reuse IDs. An item has this brief structure:

```markdown
## FB-001 — Short title
- Received / updated: date and time including time zone
- Source and request: a faithful summary of the user's message and context
- Expected result: an observable condition of fulfillment
- Status: new
- Permission / decision: assigned for realization, or a proposal waiting for a decision
- Impact on the plan: no plan change, or links to AC / D / T / Q and the affected documents
- Result and verification: changed files, a brief conclusion, links to check evidence
- Acceptance by the user: not expressed, or an evidenced reply with date
- History: substantial changes of the assignment and status with reason, blockages and the next step
```

Use statuses with a clear meaning:

| Status | Condition |
|---|---|
| new | The feedback is captured, the impact not yet assessed. |
| awaiting clarification | A decision is missing; state the question and the blocked part. |
| ready | The assignment is clear, authorized and the needed plan update is done. |
| in progress | Implementation or a fix of a failed verification is under way. |
| implemented | The change is integrated, but the relevant verification is not finished yet. |
| verified | The expected result is met and evidenced by the corresponding checks. |
| postponed | State the reason and the user's decision or an already confirmed scope boundary. |
| superseded | State the reason and a link to the successor FB; on an explicit cancellation evidence the decision. |

State an environment blockage with the current status and the next step; do not turn it into a
postponement or a successful verification. Partial fulfillment is not fulfillment of the whole point;
split independent parts into linked FB as needed. Attach a duplicate message to the existing point.
Keep a clarification under the same ID with history; link a substantially replaced request to a new ID.
Never delete the history. Reopen a newly found regression and keep the old evidence as historical, not
as valid verification of the new fix.

## Receipt and impact on the plan

Distinguish a change request, a question and a non-binding idea. A clear instruction to change is the
permission for that change; do not ask about it again. Mark a brainstorming proposal as waiting for a
decision and do not implement it automatically. On an instruction to only record, stop at the record.
Resolve new business ambiguities per the
[business questions procedure](shared/business-questions.md); independent work may
be finished. Feedback by itself does not authorize push, deploy or installation.

- A small fix within the valid assignment continues directly via programming. Record "no plan change"
  and any related task ID; do not create planning ceremony.
- A change of scenarios, acceptance criteria, contracts, scope or dependencies requires a targeted
  update via [planning](../planning/SKILL.md). Reflect the confirmed assignment in the affected PRD,
  decisions, chapters and tasks, keeping IDs and history. Limit the validation per planning to the
  changed parts and their links; do not rewrite the valid rest. Start the dependent implementation
  only after the needed decisions and the validation of the plan change.

Reopen the affected finished tasks in the progress when they no longer meet their conditions; add new
tasks per planning for new work. Keep past verifications, stating what invalidated them. Leave
unchanged tasks in their real state.

## Implementation and verification

Do every authorized implementation per [programming](../programming/SKILL.md). Pass the path to the
record, the FB IDs, the expected result, the confirmed decisions, the affected tasks and the permission
scope. Programming chooses direct work or delegation; this skill introduces no further mandatory
subagents. When the assignment changes during delegation, inform the affected agents before further
dependent work and coordinate the file owners.

After integration write the result and the status `implemented`; after the corresponding verification
`verified`. The main agent drives the checks per the project rules. Batch related changes; do not run
the whole test suite for each FB separately. Depending on the impact and the active workflow use
[Playwright](../playwright-testing/SKILL.md) or [code review](../code-review/SKILL.md). After a fix
repeat the affected scenarios and links, not automatically the whole delivery cycle. Return a failure
to the in-progress status with a reason; admit a missing check.

Update the record on receiving a message, a decision, a status change, a check and before waiting or
handover. In the summary briefly state the resolved IDs, their results and the remaining points with
reasons. `verified` does not mean acceptance by the user; record that separately only from the user's
reply. Standalone use of this skill does not activate feature-delivery or its permission to commit. In a
running delivery take over the valid permissions for the confirmed scope.
