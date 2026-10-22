---
name: code-review
description: Reviews the working tree, a branch or selected commits with perspective-based review subagents, independent verification and a synthesis. Use on a request for code review; it clarifies the scope, raises business questions and can hand fixes to programming.
---

# Code review

Before starting, resolve the [project context](shared/project-context.md) and follow the
[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.

The result is evidenced, verified findings, recommendations and, where needed, user decisions.
Review agents do not fix code. Fixes are a separate phase after the synthesis, if the user requests them.
Within [feature-delivery](../feature-delivery/SKILL.md), take the fix mode and the fixed scope of the
whole feature, including relevant uncommitted changes, from the orchestrator; interim commits do not
shrink the scope.

## 1. Clarify the assignment

Do not repeat questions the assignment or the conversation already answered. Get missing information
with the question tool. Ask together about the unclear scope and the expected output:

- **Working tree:** staged and unstaged changes against `HEAD` plus new untracked files, unless the user
  narrows the scope. A bare `git diff` is not enough. Respect ignored files and the protection of secrets.
- **Current branch:** changes from the common ancestor with the specified base branch to the current `HEAD`.
  Git does not record which branch a branch was created from; inspect the available metadata and local
  history, and confirm an unclear base branch with the user instead of assuming `main` or upstream.
- **Commits:** a concrete range or selection. Clarify the endpoints and whether to review the resulting
  diff or each commit. Do not include uncommitted changes without support in the assignment.
- **Output:** present the review only, or incorporate the verified findings via `programming`.
  Existing permissions apply; do not ask about the same thing again before fixes.

Until the scope is clear you may map the repository, but do not start reviewing undetermined changes.
An unclear fix mode does not block reading code; resolve it before writing.

Record the exact refs and SHAs, the file list and whether the working tree is included. For a branch
review diff from `git merge-base <base> HEAD`. For the working tree capture the reviewed form of the
files or their hashes so that everyone reads the same state; a snapshot does not require a commit,
stash or branch change. Write the reviewed diff once into the
[work directory](shared/project-context.md#work-directory), for example
`{work_dir}/review/{scope}/diff.patch`, and pass its path to the reviewers and verifiers; they read the
same diff instead of each computing it. If the reviewed code changes during the review, write the
fresh diff the same way into another file and run `refresh`: the reopened cells go to reviewers again
for the changed files and the stale findings to new verifications. Fixes made in step 6 need no
refresh; step 6 verifies them.

Track the review in the same folder with the [review tool](shared/review-tool.md). A diff a reviewer
covers in one run is one chunk: `init --single` with the perspective groups of step 2. When a reviewer
cannot cover its perspectives across the whole diff in one run, the review is large: `init`, `triage`
and `chunks` cut the diff into coherent chunks and [large reviews](references/large-reviews.md) apply
on top of the steps below.

Before `init`, check whether the folder of this scope already exists. If it does, the review was
interrupted: resume it instead of starting over. Start from `status`, then `coverage` and `findings`;
the folder holds everything a new session needs, and `log.jsonl` shows what happened before. Return
the cells of reviewer runs lost to the interruption to the queue with `set … pending`. Then write the
current diff of the recorded scope into another file and run `refresh`, also when `status` reports no
moved ref: changes in the working tree show only there. Continue with `next`. Ask the user only when
the scope itself no longer fits, for example a different base branch or a rebased branch whose diff
mostly changed; then a new review may be cheaper than a refresh.

## 2. Split the perspectives among review subagents

Read the [perspectives](references/perspectives.md) and the [output format](references/findings.md).
Go through all perspectives, assign a responsible reviewer to each relevant one and briefly justify omissions.

Split the review primarily by perspective: most reviewers take one or more related perspectives across
the whole reviewed change. A smaller part of the slots may go to specific modules or scenarios when their
size, complexity or risk justifies a separate check; this does not replace the responsibility for
covering all relevant perspectives. Before launching, state the assigned perspectives, the scope and
the reason for any module assignments. Record the perspective groups with `group`, their assignment
to chunks with `cell` and every omission with `omit`; hand cells to a reviewer with `start`.

A cross-cutting reviewer systematically goes through its whole cell, the whole agreed diff or in a
large review its chunk, including new files, and applies its perspectives to all relevant changes; the
goal is complete coverage, not sampling of risky spots. Risky parts first and deepest, then the rest.
If a reviewer cannot cover part of its cell, it names the files or sections and the orchestrator
records the cell as `partial` and arranges a follow-up; until then that coverage counts as incomplete.

The number of reviewers follows the [number of runs](shared/delegation.md#number-of-runs): the cells
that fit one run each. **X is the maximum number of review subagents** unless the user requires an exact
number. In a large review X limits the parallel reviewers of one wave, not the total: the total number
of reviewer runs is in the estimate the user approves per
[large reviews](references/large-reviews.md#4-estimate-and-approval), so say there that it exceeds X.
Without X, the wave size is [`parallel_runs`](shared/project-context.md#parallel-runs); state the split.
One reviewer may take several related perspectives; the number of perspectives is neither the number
of agents nor a required number of findings. Verification and synthesis are later phases, not a
requirement to run everything at once.
Model choice and the case of unavailable subagents follow [delegation](shared/delegation.md).

Give every reviewer:

- the exact scope, the reviewed revision and its perspectives;
- the user's assignment, known decisions and relevant plans;
- the [ground rules](shared/ground-rules.md) and the concrete paths of the project rule files relevant
  to the change, selected by you per [project context](shared/project-context.md#project-instructions);
  the reviewer reads those files, not the indexes;
- the common findings format and the ban on fixing during the review;
- how to hand over findings, questions, coverage and limitations.

A reviewer also reads the surrounding code and callers needed to judge the impact. It reports every bug
it finds, also in old code or outside the reviewed feature, marked as an existing problem outside the
change rather than a regression, and passes it to the same verification. The diff defines the mandatory
coverage, not a filter on reported bugs. A reviewer is not obliged to find something and does not report
preferences without a concrete benefit. Reviewers check by reading; requests for linters, formatters,
static analysis, tests or builds go to the main agent per the
[ground rules](shared/ground-rules.md#verification).

Keep stable finding IDs and traceable decisions. When a reviewer returns, write each finding verbatim
into `findings/{ID}.md`, index it with `finding` and the files of its location and record the cell's
coverage with `set`; reviewers stay read-only, the orchestrator keeps the record.

## 3. Resolve new business questions

Follow the [business questions procedure](shared/business-questions.md) in every phase of the
review and the fixes. When correctness depends on undetermined product behavior, do not decide for the
user and do not present an assumption as a confirmed bug. Independent work continues; findings and fixes
that depend on an answer wait. Elapsed time is not a decision.

## 4. Independent verification

The number of verifiers follows the [number of runs](shared/delegation.md#number-of-runs) over the
findings: a verifier run takes the findings that share code or a cause, typically about four, fewer
when they are hard or critical; they run in the same slots as the reviewers. A large review verifies
each wave's findings as they arrive. With no findings skip the verification phase. Do not invent
findings to give verifiers work. Every finding has a primary verifier; a critical or disputed finding
is also checked by a second one. A verifier is never the sole verifier of its own finding.

Give the verifiers the exact assignment, code, rules, user decisions, evidence and proposed fixes.
A verifier independently traces the behavior in the sources. When it needs a targeted check, it hands
the request to the main agent with its interim conclusion and ends; the main agent runs the check and
briefs a new short verifier run with the result per
[one assignment per run](shared/delegation.md#one-assignment-per-run). A reviewer's authoritative tone or agent voting is not
evidence. It also checks whether the proposed fix addresses the cause, does not break another rule and
does not change undecided product behavior.

Each finding gets **confirmed**, **refuted** or **undecidable** with evidence and reasoning. Lack of
information is not a refutation. Resolve a disagreement between verifiers with evidence or leave it
explicitly open; a business decision goes to the user. Append each verification to the finding's file
and record it with `verify`; a resolved dispute, a pending decision or a merge with `resolve`.

## 5. Synthesis by one subagent

One further subagent receives all review outputs, verifications, user decisions and the coverage map:
the paths of the finding files, the `findings --all` index and the `coverage` output. A large review
whose findings do not fit one run synthesizes in two levels per [large reviews](references/large-reviews.md#6-synthesis).
It groups duplicates by common cause and keeps all original IDs, locations and impacts; a similar
proposed fix alone is no reason to merge unrelated bugs. It separates confirmed bugs, optional
improvements, open questions and refuted findings, does not promote an unverified finding to confirmed
and returns an unverified new finding to verification. It orders the bugs by impact and adds the
recommended solution. Refuted findings stay traceable; a brief summary for the user is enough unless
the full output is requested.

The main agent runs `validate` and `coverage`, checks the synthesis against the assignment and
presents the final scope, findings, open decisions and the verification actually performed including
limitations. "No confirmed findings" is not a guarantee of correctness.

## 6. Optional fixes

In presentation mode the work ends with presenting the results. In fix mode hand the synthesis,
verified findings, solutions, permission scope and user answers to [programming](../programming/SKILL.md).

The fix mode covers confirmed bugs **inside the reviewed scope**. Confirmed existing problems outside the
change are always reported, but fixed only with the user's explicit consent: after the synthesis ask
once with the question tool, listing them by ID with severity, impact and the expected size of the fix,
and let the user pick all, some or none. Without an answer they stay reported and unfixed; the
Recommended mark, a timeout or the fix mode of the reviewed scope is not consent. An existing problem
that blocks a correct fix of an in-scope finding is part of that fix; say so in the question anyway. Incorporate
optional improvements only when the assignment includes them. A finding waiting on a business decision
is not fixed from the recommendation alone.

Verify the fixes and their impacts in a targeted way with new short verifier runs over the fixed
findings; do not resume the original reviewers and do not repeat the whole review without a new reason.
