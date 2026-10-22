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
- Set the risk of every chunk; security, money, data consistency, migrations and shared contracts are
  high.
- `full` is the normal review. `light` suits lockfiles, vendored and generated code, build output and
  pure renames: check that they match their source or the declared update, that nothing unexpected is
  hidden in them and that a rename has no content change. `excluded` needs a reason and the user's
  consent in the approval below; it is listed as unreviewed in the result.

## 2. Map of the change

Before the first wave one explorer run builds a short map of the change: the modules, the changed
public contracts (APIs, schemas, events, configuration, shared types) and who uses them. Save it as
`map.md` in the review folder. Every reviewer gets the map with its cells, so that it can judge the
impact beyond its chunk without reading the whole diff.

## 3. Cells

Group the perspectives once per the [combination rules](perspectives.md#how-to-combine-perspectives)
and use the same groups for all chunks, so that findings stay comparable. Assign the relevant groups to
each chunk and `omit` the others with a reason; no relevant area may disappear in any chunk.

Some perspectives cannot be judged inside one chunk. Give them cells of an `--integration` chunk that
runs after the local cells, works from the map and the wave summaries and reads code only where a link
needs it:

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

A wave is up to the wave size of parallel reviewer runs (6 by default, or the user's X). Each run takes
the cells from `next` that belong together, usually several groups of one chunk or one group of a few
small chunks, recorded with `start`. Give it the brief of a reviewer from the
[skill](../SKILL.md#2-split-the-perspectives-among-review-subagents) narrowed to its chunk files, plus
the map.

When a run returns:

1. Write each finding verbatim into `findings/{ID}.md` and index it with `finding` and the files of
   its location. From then on work with the index and the files, not with the returned text.
2. Record the coverage with `set`: `covered`, or `partial` with the concrete unchecked files or
   sections, which `next` offers as a follow-up first.
3. Add a few lines to `waves.md` in the review folder: what the run found about contracts and links to
   other chunks. The integration cells and the synthesis read it.
4. Start the next ready cells in the freed slots and brief verifiers for the new findings at the same
   time; verification does not wait for the end of all waves. The number of verifiers follows the
   [verification rules](../SKILL.md#4-independent-verification) per batch of new findings.

A run lost to an interruption returns its cells to the queue with `set … pending`; resuming an
interrupted review follows [clarify the assignment](../SKILL.md#1-clarify-the-assignment).

## 6. Synthesis

When the findings do not fit one synthesis run, synthesize in two levels: one run per set of related
chunks over their findings files, then one final run over the partial syntheses, the integration
findings and the coverage. The final run merges duplicates across the sets by common cause and keeps
every original ID. Before presenting, `coverage` and `validate` must show no gap that the result does
not name as a limitation.
