---
name: handoff
description: Prepares a handover of work in progress to another LLM tool as a temporary Markdown document outside the repository plus a prompt to copy manually. Use on a request for a handoff or to pass context to another agent; a plain status question does not start this workflow.
---

# Handoff

Before starting, resolve the [project context](shared/project-context.md) and follow the
[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.

Prepare a handover that lets another agent continue in the same local checkout without access to the
original conversation. Write the document and the final prompt in English, whatever language the
conversation uses; quote the user's decisions in English too, keeping only product terms that have no
English equivalent. The handover is a snapshot of the current state, not a new assignment or an
extension of permissions.

## Preparation

1. From the conversation capture the goal, scope, completion conditions, the user's latest
   clarifications, approved decisions and their reasons. Separate approved steps from proposals and
   questions waiting for an answer. If the user set a focus for the handover, respect it.
2. Verify the absolute path of the checkout, the current branch (or detached HEAD), the HEAD commit and
   the working tree state. Use `git status --short`, an overview of staged and unstaged changes and
   targeted reading of the relevant diffs and untracked files. Include uncommitted work in progress too;
   the diff alone does not carry its intent.
3. Compare the state with the existing plan, tasklist and relevant files. Refer to the plan as the
   source of tasks; do not create a second independent copy of it. State any discrepancies between the
   plan and reality. Do not claim others' changes as your own; mark an unknown origin.
4. Capture the verification so far, failed attempts and the operational context needed to continue.
   Mark what you have no evidence for as unknown or a hypothesis. Do not rerun test suites for the sake
   of the handover; for results state whether changes followed them and what remains unverified.

During the preparation do not fix the implementation, do not edit the plan or tasklist and do not
create a commit, stash or new branch. Do not launch another LLM tool and do not pass the work to it
automatically. If delegated work is still running, request its state and make sure it no longer writes
into the same checkout after the snapshot is taken; record unfinished operations explicitly.

## Temporary document

Store a single Markdown file in the system temporary directory, never in the project. Create a unique
file with `mktemp` (owner-only permissions), using the
[handoff prefix](shared/project-context.md#handoff-prefix), for example:

```bash
mktemp "${TMPDIR:-/tmp}/<handoff_prefix>-handoff-$(date +%Y%m%d-%H%M%S)-XXXXXX.md"
```

Use the path actually returned. Do not overwrite an existing handover and do not delete the file when
done. Write the content with the file tool or a safely quoted heredoc so that the document text is not
evaluated as a shell command.

The document should contain the following; shorten or omit unimportant parts:

- **Identification:** creation time including time zone, absolute path of the checkout, branch and the
  full HEAD hash. Warn that the new agent must check for changes since the handover.
- **Goal and completion:** the required result, scope and concrete completion conditions.
- **User decisions:** preferences, constraints, authorized steps and proposals not yet approved. Keep
  the reasons of decisions the new agent might otherwise reopen.
- **State of work:** finished, in-progress and remaining parts. Distinguish implemented from verified
  behavior. Explain the intent of changes in progress.
- **Files and Git:** relevant paths with a short explanation, staged/unstaged/untracked state and known
  foreign changes. Use absolute paths or define the root of relative paths explicitly; do not refer only
  to the chat history or internal tool IDs.
- **Plan and rules:** paths to the existing plan and tasklist, approved mockups (also those kept only
  in the work directory), relevant materials and the entry file of the project instructions
  (`AGENTS.md`, `CLAUDE.md`). Do not copy the project rules; the new agent loads them itself.
- **Verification:** checks actually performed, commands, results, limitations and subsequent changes.
  State clearly what was not run or finished.
- **Obstacles and hypotheses:** open questions, evidenced bugs, failed attempts and their results, so
  that the next agent does not repeat the same work.
- **Operational context:** needed services, available artifacts and operations in progress. Terminal
  sessions, running agents and tool connections do not carry over automatically; state how to restore
  the needed environment if known.
- **Continuation:** the concrete first step and a brief order of the next steps within the authorized
  assignment. If waiting on a user decision, mark it clearly.

Do not include passwords, tokens, secret values or whole environment files. For configuration state
only its location and the established way of loading it. Do not copy the whole conversation or large
diffs; fit the length to the complexity of the work in progress.

## Check and handover to the user

Read the resulting document and verify that it matches the current state, the links lead to available
files and the first step is doable without the original chat. Check that it contains no secrets and that
no handover file was created in the project.

Finally provide the link to the created file and a prompt to copy manually with the absolute paths
filled in, for example:

> Continue the work in `<checkout>` per the handover in `<handoff.md>`. First load the project
> instructions (`AGENTS.md` / `CLAUDE.md`) and the linked rules. Check whether the current branch, HEAD and working
> tree match the snapshot in the handover; keep and take into account any newer changes. Respect the
> recorded decisions and the user's permission scope and continue with the first unfinished step. If a
> step requires consent not yet given, ask for it first.

Briefly remind that the temporary directory may be cleared on restart. End with the handover and do not continue the
original implementation.
