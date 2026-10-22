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
| `diff.patch` | The reviewed diff with rename detection (`git diff -M …`), written once before `triage`; everyone reads this file. |
| `review.json` | Live state: revision, chunks, perspective groups, cells, waves, the approval and the finding index. |
| `log.jsonl` | Append-only history of every change and of recorded checks, decisions and notes. |
| `triage.json` | The proposal of chunks from `triage`, edited by the orchestrator before `chunks`. |
| `findings/{ID}.md` | One finding in the [findings format](../../code-review/references/findings.md), with its verifications appended. |

A **chunk** is a coherent part of the diff (files that belong together) with a risk (`high`, `medium`,
`low`) and a treatment (`full`, `light`, `excluded`). A **group** is a set of perspectives one reviewer
takes. A **cell** is one group on one chunk, `C03/G1`; it is `pending`, `running`, `covered`,
`partial` (with the unchecked files or sections) or `omitted` (with the reason). A chunk created with
`--integration` has no files of its own; its cells cover the links between chunks and become ready
only after all other cells are closed.

## Commands

| Command | Use |
|---|---|
| `init --scope S --base REF --head REF [--working-tree] [--wave-size N]` | Create the folder state; the wave size is the number of parallel reviewers, 6 by default. |
| `init … --single --groups G1="Correctness and regressions;Testability and risk coverage" G2="…"` | A review one reviewer run covers: write `diff.patch` first, then one call creates the chunk `C01` with the whole diff, the groups and their cells. Skip `triage`, `chunks`, `group` and `cell`. |
| `triage [--chunk-lines N]` | Parse `diff.patch`, classify files (logic, lockfile, vendor, generated, build output, rename only, binary) and propose chunks by directory within the line budget (2500 by default) into `triage.json`. A suggestion only. |
| `chunks triage.json` | Load the edited proposal. |
| `chunk ID --title T [--files …] [--risk R] [--treatment T] [--integration] [--reason R]` | Add or change one chunk; `excluded` needs a reason. |
| `group G1 --perspectives "…" "…"` | Define a perspective group by the names in the [perspectives](../../code-review/references/perspectives.md). |
| `cell C03 G1 G2` / `omit C03 G4 --reason "…"` | Assign groups to a chunk, or record why a group is not relevant to it. |
| `estimate` | Chunks, files and lines by treatment, open cells and the waves still needed. |
| `approve --coverage full\|risk_first [--note …]` | Record the user's decision on the estimate; `next` refuses more than one wave without it. `risk_first` leaves the low-risk cells open and reported. |
| `next [--limit N]` | Cells to brief now: follow-ups of partial cells first, then by risk, up to the free slots. |
| `start --owner R3 C03/G1 [C03/G2 …]` | Hand cells to one reviewer run; a start while other cells run joins their wave. |
| `set C03/G1 covered\|partial\|pending\|omitted [--unchecked …] [--reason …]` | Record the reviewer's coverage; `pending` returns a cell of a lost run to the queue. |
| `finding R3-01 --cell C03/G1 --kind bug --severity high --title "…" [--outside]` | Index a finding after writing `findings/R3-01.md`; IDs are stable and unique. |
| `verify R3-01 confirmed\|refuted\|undecidable --verifier V2` | Record one verification; differing verdicts make the finding `disputed`. Refuses the finding's own reviewer. |
| `resolve R3-01 STATUS --reason … [--duplicate-of R1-04]` | Final status after a resolved dispute, a business decision (`awaiting_decision`) or a merge (`duplicate`). |
| `findings [--status S] [--chunk C] [--all]` | Compact index ordered by severity; refuted and duplicates only with `--all`. |
| `coverage` | Open, partial and omitted cells, excluded chunks and diff files in no chunk. |
| `status` | Overview: approval, waves, cells, running reviewers, finding counts, missing second verifiers. Start here after an interruption. |
| `validate` | Check the state, the file coverage of `diff.patch`, finding files and the verification rules. Exit code 1 on an error. |
| `log check\|decision\|note key=value …` | Append a record, for example `log check subject="make test" result=pass`. |

The tool records, it does not judge: the chunking, risks, relevance of perspectives, whether a reviewer
really covered its cell and whether a finding holds stay the agent's decisions. Without Python keep the
same folder and rules by hand.
