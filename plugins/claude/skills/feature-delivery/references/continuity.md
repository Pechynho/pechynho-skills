# Checkpoints and takeover of work

## One persistent progress

Extend the existing `{plans_dir}/{feature}/progress.json` per the
[planning format](../../planning/references/artifacts.md); do not create a competing state file.
For the whole pass add a `delivery` object:

| Field | Content |
|---|---|
| `status` | `in_progress`, `awaiting_user`, `blocked`, `ready_for_user` or `accepted`. |
| `phase` | `planning`, `implementation`, `playwright`, `code_review`, `fixes` or `handoff`. |
| `authorization` | The source of the whole-workflow assignment, the confirmed scope, limitations and separate consents (e.g. push). |
| `git` | Branch, immutable `base_commit`, initial uncommitted changes and their ownership, last known HEAD, last checkpoint and push information. |
| `findings` | Stable finding IDs, source of the check, affected tasks, status, fix and evidence of the follow-up verification. |
| `environment` | Dev URL, identification of the verified environment and test data, changed temporary settings and cleanup. |
| `feedback` | Optional path to `feedback.md` relative to the plan folder and the IDs of the FB currently handled; without a copy of their statuses. |

Use the existing `checks`, `open_questions` and `handoff`; do not duplicate their content into `delivery`.
For checks keep the command or scenario, date, actual result, verified revision and, where applicable,
the hashes of uncommitted files. A change of the affected code may invalidate the evidence. Mark a
finding as resolved only with the corresponding verification; link open questions by their IDs.

User feedback and its resolution are kept by [feature-feedback](../../feature-feedback/SKILL.md) in
`feedback.md`. Findings from checks stay in `findings`; when a feedback item relates to them, link them
by ID instead of creating a second record of the same finding. After new feedback update the affected
tasks and the delivery phase; do not rewrite the history of old checks or the user's acceptance.

`handoff` contains the concrete next step, the files and tasks in progress, uncommitted changes, the
state of delegated work, blockages and the commands needed to resume. Only the main orchestrator writes
the progress. Save changes by atomically replacing valid JSON so that an interruption does not leave
half a file. For an older plan keep the IDs and history; add the needed fields without overwriting the
real state.

The permanent summary of results must suffice without live agents and without the content of the
[work directory](../shared/project-context.md#work-directory). Large logs and screenshots may stay in the working directory, but write their substantial
conclusions into the progress; admit missing evidence on takeover. Do not store secrets, database dumps
or sensitive test data in Git. The temporary planning notes are not the only handover document.

## When to save and commit

Update the progress after a decision, an integrated milestone, a check and its fixes, before waiting
for the user and before the handover. Ongoing writes protect against a sudden restart or exhausted
limits; do not rely on managing a final write.

The ongoing commit is made by the main agent after a coherent milestone. Before it, the agent reads the
diff, stages only the changes that belong, including the current progress, and checks the staged diff.
Do not commit others' work. Include the related changes of `feedback.md` and the plan in the checkpoint.
Drive the checks by the impact of the change and the project rules; do not rerun the whole suite just
to write the progress. An emergency checkpoint of work in progress is possible with a clearly marked
state and the checks not performed, not as a claim of completion. Do not bypass failed Git hooks
automatically.

A commit cannot contain its own resulting SHA. The progress in a checkpoint refers to the previous
known commit and describes the milestone being saved; get the SHA of the new checkpoint from Git and
record it at the next update or in the final handover. Do not create an endless series of commits or
amends for it. After a failed commit or push record the actual result. A local commit is not a remote
backup: push only with the user's corresponding permission.

At the end of the implementation phase and after the review phase of a larger feature, once the
checkpoint is saved, offer the user a fresh session resumed per
[resuming after an interruption](#resuming-after-an-interruption). The progress must already carry
everything the next session needs; a deliberate resume from the recorded state keeps more than the
automatic compaction of a long conversation. The user decides whether to restart.

## Resuming after an interruption

1. Load the plan, decisions, progress, the existing `feedback.md` and the current Git state, including
   new and uncommitted files. Check the FB in progress and their links to tasks.
2. Compare the expected branch, base and checkpoint with reality. Keep foreign or unclear changes and
   clarify their ownership. Do not fill in assumed results of missing steps.
3. Verify the state of tasks in progress from the files, not from the availability of former
   subagents. Do not treat an old process ID or agent session as still alive; only then delegate again
   if needed.
4. Check the availability of the dev environment, test data and evidence. Repeat already successful
   checks only when a change or a concrete uncertainty invalidated their result.
5. Continue with the nearest unmet step. Respect permissions granted earlier for the same scope; an
   open business question stays open until the user's actual answer.
