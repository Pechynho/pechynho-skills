# Plan tool

`plan.py` next to this document works with a plan in the
[planning format](../../planning/references/artifacts.md): it reads the tasklist, derives the state and
changes `progress.json` and `log.jsonl` consistently. Prefer it to reading whole task files and to
editing the progress by hand; it saves context and checks the rules a manual edit can break.

Run it from anywhere with the path of the plan folder (Python 3.8+, standard library only):

```bash
python3 <skill directory>/shared/plan.py {plans_dir}/{feature} <command>
```

| Command | Use |
|---|---|
| `init` | Create `progress.json` and `log.jsonl` for a new tasklist. |
| `validate` | Check JSON, unique IDs, parents, dependencies and their cycles, references, coverage of the PRD criteria, the mockup index, the progress and the log. Exit code 1 on an error. |
| `status` | Derived overview: phase, counts, blocked and running tasks, open questions, unresolved findings, ready tasks. |
| `next` | Tasks whose dependencies, including those of their parents, are done, and parents whose subtasks are finished and wait for integration. |
| `show T-001` | One task with its status, dependencies, subtasks, consumers and log records; enough for a brief. |
| `set T-001 in_progress --owner worker` | Change a status; also `blocked --blocker Q-002`, `done --evidence "…"`, `cancelled --reason "…"`. Refuses `done` with unfinished subtasks or dependencies. |
| `log check subject="make test" result=pass revision=abc123` | Append a record; types `check`, `finding`, `validation_plan`, `validation`, `checkpoint`, `note`. Values are parsed as JSON when possible (`tasks='["T-001"]'`). |
| `log validation_plan pass=V1 mode=areas cells='[…]'` | Record the cells of a validation pass per the [validation mode](../../planning/references/delegation-and-validation.md#validation-mode). Refuses a repeated pass, an unknown mode, task or chapter. |
| `log validation pass=V1 cell=A1 validators='["V-A1"]' result=… coverage=covered` | Record one validator run of a cell; `coverage=partial` needs `unchecked`. |
| `findings` | The current state of unresolved findings; `--all` includes the closed ones. |
| `validations` | The cells of the last validation pass (`--pass V1` for another): covered, partial with what is unchecked, pending, or waiting for an integration cell whose area cells are not covered yet, and the cells to brief. `--open` lists the cells not covered in all passes; a partial cell is finished in its own pass. |

The tool records, it does not judge: whether a task meets its `done_when`, whether a finding is
resolved and which checks to run stay the agent's decisions. Fields it does not manage (`plan_status`,
`implementation_status`, `open_questions`, `handoff`, `delivery`) are edited in `progress.json`
directly, keeping valid JSON. Without Python follow the same format by hand and check the same rules.
