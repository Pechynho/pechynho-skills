# Large reviews

A review is large when a reviewer cannot go through its perspectives across the whole agreed diff in
one run (see [one assignment per run](../shared/delegation.md#one-assignment-per-run)). Judge it after
the triage, not by the raw line count: lockfiles, vendored and generated code often make up most of a
huge diff. A large review keeps the same perspectives, verification and synthesis; it changes how the
work is cut and that it runs in waves. Track all of it with the [review tool](../shared/review-tool.md).

## 1. Triage

Run `triage` on the written diff and correct the proposal before loading it:

- Keep files that change together in one chunk: a module with its tests, a migration with the code that
  uses it, a template with its controller. Directory grouping is only the starting point.
- The line budget of `triage` counts changed lines, in an audit whole files. It is a starting point,
  not the size of a run.
- Set the risk of every chunk; security, money, data consistency, migrations and shared contracts are
  high.
- `full` is the normal review. `light` suits lockfiles, vendored and generated code, build output and
  pure renames: check that they match their source or the declared update, that nothing unexpected is
  hidden in them and that a rename has no content change. `excluded` needs a reason and the user's
  consent in the approval below; it is listed as unreviewed in the result.

## 2. Orientation

No run maps the change in advance; for a huge diff it would not fit one run, and each reviewer finds
the impact of its own chunk. Every reviewer gets the `overview` of the chunks with its cells, so that it
can name a link to another chunk without reading its diff. What the reviewers learn about contracts and
links goes into `waves.md` (see [waves](#5-waves)), which the integration cells and the synthesis read.

## 3. Cells

Group the perspectives once per the [combination rules](perspectives.md#how-to-combine-perspectives)
and use the same groups for all chunks, so that findings stay comparable. Assign the relevant groups to
each chunk and `omit` the others with a reason; no relevant area may disappear in any chunk.

Some perspectives cannot be judged inside one chunk. Give them cells of an `--integration` chunk that
runs after the local cells, works from `waves.md`, the `overview` and the impact the reviewers recorded,
and reads code only where a link needs it:

| Perspective | Inside a chunk | In the integration cells |
|---|---|---|
| Correctness and regressions, Security and privacy, Performance and resources, Project rules, Testability, UX | Fully | Changed contracts and their callers in other chunks |
| Data, concurrency and asynchronous processing | Transactions and local consistency | Event order, migrations and messages across modules |
| Existing solutions and unnecessary complexity | Own implementations in the chunk | Equivalents that exist in another chunk |
| Architecture, maintainability and DRY | Responsibilities inside the module | Duplicated rules, module boundaries, dependencies |
| Product and business | Scenarios implemented in the chunk | Completeness of the whole feature against the assignment |
| Operations and diagnostics | Local logging and configuration | Deployment, concurrent versions, rollback |

## 4. Estimate and approval

Show the user the `estimate`: chunks by treatment, cells, waves and reviewer runs, and the excluded
chunks. When the user gave X, state that X is the number of parallel reviewers and the total runs exceed
it; a user who meant X as the total chooses risk first or a smaller scope here. Ask with the question tool for **full coverage** or **risk first**, where the low-risk cells
stay unreviewed and are listed as such. Record the answer with `approve`. Without the approval do not
start a second wave.

## 5. Waves

A wave is up to the wave size of parallel reviewer runs (the user's X, otherwise
[`parallel_runs`](../shared/project-context.md#parallel-runs), 6 by default); pass it to `init
--wave-size`. Each run takes
the cells from `next` that belong together, usually several groups of one chunk or one group of a few
small chunks, recorded with `start`. Give it the brief of a reviewer from the
[skill](../SKILL.md#2-split-the-perspectives-among-review-subagents) narrowed to its chunk files, plus
the `overview`.

When a run returns:

1. The run has recorded its findings and the coverage of its cells itself per the
   [skill](../SKILL.md#2-split-the-perspectives-among-review-subagents); check it with `status`. From
   then on work with the index and the finding files, not with returned text. A `partial` cell lists
   the unchecked files or sections, which `next` offers as a follow-up first.
2. Add a few lines to `waves.md` in the review folder: what the run found about contracts and links to
   other chunks. The integration cells and the synthesis read it.
3. Start the next ready cells in the freed slots and brief verifiers for the new findings at the same
   time; verification does not wait for the end of all waves. The verifier runs follow the
   [verification rules](../SKILL.md#4-independent-verification) per batch of new findings.

A run lost to an interruption returns its cells to the queue with `set … pending`; resuming an
interrupted review follows [clarify the assignment](../SKILL.md#1-clarify-the-assignment).

## 6. Synthesis

When the findings do not fit one synthesis run, synthesize in two levels: one run per set of related
chunks over their findings files, then one final run over the partial syntheses, the integration
findings and the coverage. The final run merges duplicates across the sets by common cause and keeps
every original ID. Before presenting, `coverage` and `validate` must show no gap that the result does
not name as a limitation.
