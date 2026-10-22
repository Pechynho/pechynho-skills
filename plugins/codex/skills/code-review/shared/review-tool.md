# Review tool

`review.py` next to this document keeps the state of one code review in its folder,
`{work_dir}/review/{scope}/`: which parts of the diff exist, which perspectives cover them, who reviews
what in which wave, and the index of findings with their verification. Use it for every review, small
or large; a small review is one `init --single` with one chunk and one wave. Prefer it to tracking the coverage in your head or
in a hand-edited file; it keeps the state consistent and survives an interrupted session.

Run it from anywhere with the path of the review folder (Python 3.8+, standard library only):

```bash
python3 <skill directory>/shared/review.py {work_dir}/review/{scope} <command>
```

## Folder

| Path | Content |
|---|---|
| `diff.patch` | The reviewed diff with rename detection (`git diff -M …`), written once before `triage`; everyone reads this file. In an audit `init` writes it with the whole files as new files. Only `refresh` replaces it. |
| `previous/diff-NN.patch` | The diff before each `refresh`. |
| `review.json` | Live state: revision, chunks, perspective groups, cells, waves, the approval and the finding index. |
| `log.jsonl` | Append-only history of every change and of recorded checks, decisions and notes. |
| `triage.json` | The proposal of chunks from `triage`, edited by the orchestrator before `chunks`. |
| `findings/{ID}.md` | One finding in the [findings format](../../code-review/references/findings.md), with its verifications appended. |

A **chunk** is a coherent part of the diff (files that belong together) with a risk (`high`, `medium`,
`low`) and a treatment (`full`, `light`, `excluded`). A **group** is a set of perspectives one reviewer
takes. A **cell** is one group on one chunk, `C03/G1`; it is `pending`, `running`, `covered`,
`partial` (with the unchecked files or sections) or `omitted` (with the reason). A covered or partial
cell also keeps the files of its chunk its reviewer **skipped** as not relevant to its perspectives, each
with the reason; every other file of the chunk counts as reviewed. The chunk is the **core** of its
cells, which the coverage requires. The **impact** is what lies outside it: files the change affects,
which the reviewer finds by its own judgment and lists as checked or not checked. The impact never makes
a cell partial; what was not checked is reported as a limitation. A chunk created with
`--integration` has no files of its own; its cells cover the links between chunks and become ready
only after all other cells are closed.

## Who records

The orchestrator owns the structure: `init`, chunks, groups, cells, `start`, `approve`, `resolve` and
`refresh`. A reviewer or verifier records its own results with `--as ID` before the command, so that
their text does not pass through the orchestrator:

```bash
python3 <skill directory>/shared/review.py {work_dir}/review/{scope} --as R3 batch - <<'EOF'
["finding", "R3-01", "--cell", "C03/G1", "--kind", "bug", "--severity", "high", "--title", "Refund ignores the currency", "--files", "src/Refund.php:42", "--body", "# R3-01 Refund ignores the currency\n\n- **Scenario:** …"]
set C03/G1 covered --skipped "templates/refund/**=no logic of this group"
EOF
```

With `--as` the tool allows only `finding` and `set` (`covered` or `partial`) in the cells started for
that ID, `verify` under that ID, `log` and the read-only commands; every record carries `by` with the ID.
Commands lock the folder, so parallel subagents do not lose each other's records (not on Windows).
`--as` guards against mistakes, it is not access control: an agent could run the tool without it, and
that the reviewers leave the project unchanged is an instruction of their agent, not enforced.

## Commands

| Command | Use |
|---|---|
| `init --scope S --base REF [--head REF] [--working-tree] [--wave-size N]` | Create the folder state and record the SHAs of both refs; run it inside the repository. `--head` is `HEAD` by default. The wave size is the number of parallel reviewers, 6 by default. |
| `init --scope S --audit PATTERN … [--head REF \| --working-tree] …` | An audit of an area or the whole project instead of a change: write `diff.patch` with the whole files the patterns match, at the head or as they are on disk (tracked and untracked, not ignored). Each pattern has to match a file. Combines with `--single` and the rest of `init`. |
| `audit-diff FILE` | The current whole files of the audit's patterns, for `refresh`. |
| `init … --single --groups G1="Correctness and regressions;Testability and risk coverage" G2="…"` | A review one reviewer run covers: write `diff.patch` first, then one call creates the chunk `C01` with the whole diff, the groups and their cells. Skip `triage`, `chunks`, `group` and `cell`. |
| `triage [--chunk-lines N]` | Parse `diff.patch`, classify files (logic, lockfile, vendor, generated, build output, rename only, binary) and propose chunks by directory within the line budget (2500 by default) into `triage.json`. A suggestion only. |
| `chunks triage.json` | Load the edited proposal. |
| `chunk ID [--title T] [--files …] [--risk R] [--treatment T] [--integration] [--reason R]` | Add or change one chunk; omitted options keep their values (a new chunk needs a title and is `medium`, `full`); `excluded` needs a reason. |
| `group G1 --perspectives "…" "…"` | Define a perspective group by the names in the [perspectives](../../code-review/references/perspectives.md). |
| `cell C03 G1 G2` / `omit C03 C05 --groups G4 --reason "…"` | Assign groups to a chunk, or record why groups are not relevant to chunks. |
| `overview` | One line per chunk: risk, treatment, files, title and directory; the orientation a reviewer gets about the rest of the review. |
| `estimate` | Chunks, files and lines by treatment, open cells and the waves still needed. |
| `approve --coverage full\|risk_first [--note …]` | Record the user's decision on the estimate; `next` refuses more than one wave without it. `risk_first` leaves the low-risk cells open and reported. |
| `next [--limit N]` | Cells to brief now: follow-ups of partial cells first, then by risk, up to the free slots. |
| `start --owner R3 C03/G1 [C03/G2 …]` | Hand cells to one reviewer run; a start while other cells run joins their wave. |
| `set C03/G1 [C03/G2 …] covered\|partial\|pending\|omitted [--unchecked …] [--skipped "PATTERN=REASON" …] [--impact …] [--impact-unchecked …] [--reason …]` | Record the reviewer's coverage; `pending` returns a cell of a lost run to the queue and drops its skips and impact. `--unchecked` takes files of the chunk, or sections by name; `--skipped` takes files of the chunk. `--impact` and `--impact-unchecked` take files outside the chunk and do not change the status. A follow-up of a partial cell keeps the earlier skips and adds to the impact. |
| `finding R3-01 --cell C03/G1 --kind bug --severity high --title "…" [--files …] [--outside] [--body TEXT\|-]` | Index a finding; `--body` writes `findings/R3-01.md` with its full text (refused when the file exists), otherwise the file must exist; IDs are stable and unique, made of letters, digits, `-` and `_`. `--files` names the files of its location (a `:line` suffix is dropped; a file outside `diff.patch` gets a warning); without them `refresh` judges the finding by its whole chunk. |
| `verify R3-01 [R3-02 …] confirmed\|refuted\|undecidable --verifier V2 [--note TEXT\|-]` | Record a verification of each finding, `--note` appended to its file as the evidence; with `--as` the verifier is that ID; differing verdicts make a finding `disputed`. Refuses the finding's own reviewer. |
| `resolve R3-01 [R3-02 …] STATUS --reason … [--duplicate-of R1-04]` | Final status after a resolved dispute, a business decision (`awaiting_decision`) or a merge (`duplicate`). |
| `findings [--status S] [--chunk C] [--all]` | Compact index ordered by severity; refuted and duplicates only with `--all`. |
| `coverage` | Open, partial and omitted cells, skipped files by cell and reason, the impact not checked, excluded chunks and diff files in no chunk. |
| `refresh FILE [--dry-run]` | Compare a fresh diff of the same scope, written the same way as `diff.patch` into another file (moved into place when it lies in the review folder), with `diff.patch` file by file; an audit writes it with `audit-diff`. Changed and new files reopen the covered and partial cells that cover them as `partial` with those files unchecked (integration cells by any changed or new file); a partial cell whose unchecked files all left the diff becomes `covered`; the skips of changed and removed files are dropped; open findings on changed or removed files become `stale` with their previous status and verifications kept in their history; verify them again and resolve a former `awaiting_decision` again if the decision is still open. New files go into a new chunk without cells (in a `--single` review into `C01`), removed files leave their chunks. Refuses while a running cell covers a changed file. |
| `status` | Overview: approval, waves, cells, running reviewers, finding counts, missing second verifiers, stale findings and refs that moved since `init`. Start here after an interruption. |
| `validate` | Check the state, the file coverage of `diff.patch`, finding files and the verification rules. Exit code 1 on an error. |
| `log check\|decision\|note key=value …` | Append a record, for example `log check subject="make test" result=pass`. |
| `batch FILE\|-` | Several of `chunks`, `chunk`, `group`, `cell`, `omit`, `approve`, `start`, `set`, `finding`, `verify`, `resolve` and `log`, all or nothing. |

Record what a run returned in one call per [several records in one call](tool-batches.md): the findings,
the coverage and the skips of its cells together in one `batch`.

**Patterns.** File arguments (`--files`, `--unchecked`, `--skipped`, `--impact`, `--impact-unchecked`,
`--audit` and the files of `chunks`) take git-like globs: `*` and `?` within a directory, `**` across
directories, a trailing `/` for a whole directory, for example `"templates/**/*.html.twig"`. Quote them
so that the shell does not expand them. An item that names a file exactly is that file, also with `[` in
its name (`app/[id]/page.tsx`); otherwise a pattern is matched against the files of `diff.patch` (the
repository for `--impact`, `--impact-unchecked` and `--audit`), stored as the files it matched and
refused when it matches nothing; a file that appears later is not covered by an earlier pattern.

The tool records, it does not judge: the chunking, risks, relevance of perspectives, whether a reviewer
really covered its cell and whether a finding holds stay the agent's decisions. Without Python keep the
same folder and rules by hand.
