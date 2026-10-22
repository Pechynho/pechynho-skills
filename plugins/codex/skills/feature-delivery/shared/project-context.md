# Project context

The skills are project-agnostic. Everything that differs between projects is resolved here once, at
the start of a skill run, and then passed on to subagents as concrete values and paths.

## Project instructions

The project instructions are the entry file the tool loads (`AGENTS.md`, `CLAUDE.md` or both) and
every file they tell you to read. They take precedence over the defaults on this page. When the
instructions are an index of rule files, select the rule files relevant to the task yourself and pass
their **concrete paths** to subagents, together with the [ground rules](ground-rules.md); do not pass
only the index. A summary in an index does not replace reading the detailed rule.

Wherever a skill says "the project rules", it means these instructions and the rule files they link.
Closed product and technical decisions recorded by the project are inputs too; do not reopen them
without a new agreement.

## Skill settings

A project may set the values below in its instructions, typically under a heading such as
`## Agent skills`. A missing value uses the default. Do not ask the user for a value the default or the
project already answers; ask only when a value is needed and neither gives a usable answer.

```markdown
## Agent skills
- plans_dir: docs/plans
- work_dir: var/agent-work            # optional; default is outside the repository
- checks: `make lint`, `make test`    # what must pass before work counts as done
- dev_env: docs/dev-environment.md   # how to reach the dev app, test accounts, data preparation
- handoff_prefix: myproject
- parallel_runs: 6                    # subagent runs at the same time
```

### Plans directory

`plans_dir`, default `docs/plans`. Versioned plan documents, progress and feedback records live in
`{plans_dir}/{feature}/`. The skills write this location as `{plans_dir}/{feature}/`.

### Work directory

`work_dir`, default outside the repository:

```bash
root=$(git rev-parse --show-toplevel)
echo "${TMPDIR:-/tmp}/agent-work/$(basename "$root")-$(printf %s "$root" | cksum | cut -d' ' -f1)"
```

The path is unique per checkout (worktrees of one repository get different directories). Use it for
everything a skill produces only as working material: planning notes, review diffs, one-off and
click-through scripts, logs, screenshots and other evidence. Create subdirectories per skill and
subject, for example `{work_dir}/planning/{feature}/notes.md` or `{work_dir}/review/{scope}/diff.patch`.

Never put working material into versioned content. When a project sets `work_dir` inside the
repository, it must be ignored by Git; check it with `git check-ignore` before the first write and
fall back to the default otherwise. The work directory may be cleared at any time (for example `/tmp`
on restart): anything a later session needs must also be summarized in the versioned plan or progress.

### Checks

`checks`: the commands that must pass before work counts as done (lint, static analysis, tests, build)
and how to run them, for example inside a container. Without a project value, derive them from the
project instructions, the README, the task runner, the package manifests or the CI configuration, and
state which commands you chose. If they still cannot be determined, ask once.

### Dev environment

`dev_env`: how to start and reach the dev application, the test accounts and roles, how to prepare
data and how to verify that the target is the dev database. Without it, look for the information in the
project instructions and the README. For a worktree, determine whether services run from that checkout
or a shared workspace and which revision they serve. Coordinate shared services and data preparation
through the main agent; do not assume containers or a dependency on the main checkout.
Never guess that an environment is dev: an account name or the
look of a page is not proof. Without a verifiable dev environment, browser testing that writes data
waits.

### Parallel runs

`parallel_runs`, default 6. The number of subagent runs one skill keeps going at the same time; the
rest waits for a free slot. A lower environment limit on concurrent subagents wins, and a number the
user gives for the current run replaces it. How it is used is in
[delegation](delegation.md#number-of-runs).

### Handoff prefix

`handoff_prefix`, default the basename of the repository root. Used in the name of the temporary
handoff document.

## Tools

The skills name capabilities, not exact tool names. Map them to the current environment:

| Capability | Codex |
|---|---|
| question tool | the user-input tool when the current mode offers one; otherwise ask in the conversation and pause only work that depends on the answer |
| subagent | spawn a subagent; the custom agents of this collection are listed in [delegation](delegation.md#agents-of-this-collection) |
| follow-up to a finished subagent | send input to the same agent thread, only within the window described in [delegation](delegation.md#one-assignment-per-run) |
| browser | Playwright MCP (headless) or own Playwright scripts |

When a capability is unavailable, say so and use the fallback the skill describes; never present your
own work as the result of a missing independent step.
