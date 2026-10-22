# Delegation and model choice

The main agent chooses the split of work dynamically. The goal is sufficient quality at a reasonable
cost in context, coordination and time. For small changes it usually works alone. This reference is
the single place for model choice; other skills link here instead of repeating it.

## Model by task

Work is delegated to one of two tiers. The [agents of this collection](#agents-of-this-collection) fix
the tier, the tools and the sandbox per role, so pick the agent rather than a bare model.

| Tier | Model |
|---|---|
| Stronger | the newest SOL model available, for example `gpt-6.1-sol` |
| Weaker | the newest LUNA model available, for example `gpt-6-luna` |

Use the identifiers available in the current environment; do not invent names or versions. If the
requested variant is unavailable, choose a suitable available alternative and state the limitation.

- **Weaker tier** only for a bounded task with a precise brief that names an existing implementation
  or test to follow, has a clear contract and does not touch access, billing, limits, data lifecycle,
  concurrency, security or an unclear cause. Typical cases: translations of keys and texts, mechanical
  edits with an exact list of places, tests of behavior the assignment defines unambiguously, fixes of
  verified findings of low or medium severity and assembly of the JSON tasklist from a finished
  design. Within a plan, a task whose `complexity` and `risk`
  are both `low` and confirmed by the validation record in the plan log meets this. Any other task,
  and any work without a plan, is judged by the main agent against the same criteria; in doubt it goes
  to the stronger tier.
- **Stronger tier** for everything else: unclear or complex logic, interface and architecture design,
  many dependencies, root-cause hunting, security, payments, data consistency and concurrency, plan
  design, validators, reviewers, verifiers, synthesis, exploratory testing and visual judgment.
- The number of changed lines alone does not pick the model: large mechanical work may suit the weaker
  tier, a short payment or permission change needs the stronger judgment. The number of agents
  follows the [number of runs](#number-of-runs), not the number of files.
- Before every launch state in one line the chosen agent, its tier and the reason.

## Agents of this collection

The collection ships these custom agents (installed into `~/.codex/agents/` by the installer, which
resolves the newest SOL and LUNA models; see the repository README); spawn them by name.

| Agent | Tier | Sandbox | Use for |
|---|---|---|---|
| `pechynho_worker` | stronger | inherited | implementation with tests, plan authoring, fixes needing judgment |
| `pechynho_worker_light` | weaker | inherited | bounded work that meets the weaker-tier criteria above |
| `pechynho_analyst` | stronger | `read-only` | plan validators, review synthesis, exploration |
| `pechynho_reviewer` | stronger | `workspace-write`, to record its results into the review folder in the work directory; it does not edit the project | code reviewers and finding verifiers |
| `pechynho_browser_tester` | stronger | inherited | click-through and visual testers of [playwright-testing](../../playwright-testing/SKILL.md) |

If the custom agents are not installed, use the built-in `worker` or `explorer` agent with the tier's
model and state the role restrictions in the brief.

The agent definitions carry only the role and its limits; the task, the scope and the rules always come
from the brief below.

If the weaker model keeps floundering, needs a new domain decision or exceeds the contract, the main
agent refines, splits or takes over the assignment, or hands it to the stronger model. Do not continue
blind attempts just because the cheaper variant was chosen first.

## One assignment per run

The cost of a run grows faster than its length: every call sends the whole context again. Reads from
the cache are cheaper than new tokens, but over a long run they become the largest cost item, and the
context grows with each call. Short, bounded runs are also more reliable than long ones.

- One run has one assignment with a clear end: one plan task or subtask, one set of review
  perspectives, one group of test scenarios, one batch of fixes. Aim at about 80 tool calls. A run that
  passes about 120 calls and is not close to done stops at a clean boundary, with consistent code, the
  written tests and notes on what remains, and returns a handover; the main agent briefs a new run for
  the rest. The count is a guide: a few large outputs weigh as much as dozens of small ones, so
  [working with tool output](ground-rules.md#working-with-tool-output) applies throughout.
  Plan tasks are sized for this per [task size](../../planning/references/artifacts.md#task-size).
- Resume a finished subagent only within about five minutes, while its cache is alive, and only for a
  small follow-up of the same assignment: a clarification of its result or a fix of a failure in what it
  just delivered. A run resumed after the cache lifetime writes its whole context to the cache again at the
  higher price and keeps growing from that size. Do not resume one for the next round or after a longer
  pause; brief a new run with the current diff, the findings or scenarios and the relevant files.
- A subagent never waits: no `sleep` loops, no polling of files or processes, no blocking commands with
  long timeouts. When it needs a build, a worker, a check result or anything only the main agent can
  provide, it records the request, finishes the independent part and ends with a handover. The main
  agent obtains the result and briefs the continuation.
- Pass context through the brief and files, not by keeping an old agent alive.

## Number of runs

The number of subagent runs follows the work, not a fixed count. One rule for every skill:

- **Count units of work.** A unit is one assignment that fits one run, per the rule above. The number
  of runs is the number of units: not the number of files, perspectives or areas, and not a number a
  skill names for the typical case. Merge small units that share their context into one run; split a
  unit that does not fit.
- **Split by area when one run cannot hold everything.** Each run then reads only its area plus a
  short shared map of the whole (the goal, the decisions, the contracts between areas and who uses
  them), instead of everyone reading everything; this is where splitting saves context. Links between
  the areas get their own integration run that works from the map and the area results and reads the
  sources only where a link needs it.
- **Limit what runs at once, not the total.** Keep at most
  [`parallel_runs`](project-context.md#parallel-runs) runs going and start the next unit in a freed
  slot; shared resources (one browser session, the same test data, the same file) lower that number or
  sequence the runs. A large total that needs several rounds is stated to the user before it starts.
- **A user's number is binding.** When the user gives one, it is a maximum unless they say it is
  exact; when it is smaller than the units, combine units or ask what to leave out, never drop an area
  silently.
- Before launching, state the units, the number of runs, what runs in parallel and the reason in a few
  lines.

## When subagents are unavailable

If the environment does not support subagents at all, say so, agree a fallback with the user and do the
available part yourself. Do not present your own reading as their work, do not call your own check
independent, and do not mark a plan as validated or a review as verified when the independent step did
not happen.

## Subagent brief

Especially for the weaker tier prepare a precise, self-contained brief. Write it, every further message
to the subagent and the expected handover in English per the
[ground rules](ground-rules.md#language), whatever language the user uses.
Do not refer only to the number of a plan item and do not rely on the subagent having inherited the
whole conversation. Pass the relevant context without unrelated history:

1. **Result:** what changes, why, and which behavior must be preserved.
2. **Scope and ownership:** concrete files or modules, the task boundary and the concurrent work of others.
3. **Contract:** inputs, outputs, interfaces, error and edge cases; what the user has already decided.
4. **Rules and patterns:** the [ground rules](ground-rules.md), the concrete project rule files (not the
   indexes), the resolved [project context](project-context.md) values the task needs (for example
   `work_dir`), plus the relevant existing implementations and test patterns. A summary in an index does not replace reading the detailed rule.
5. **Completion conditions:** observable behavior, the expected tests in the existing infrastructure,
   the limits of fixes and the expected size of the run with the point at which to stop and hand over.
6. **Verification:** no running of linters, formatters, static analysis, tests or builds; send the
   requests and the reasons to the main agent and do not wait for the result.
7. **Escalation:** when to come back with a question instead of improvising, especially on a contract
   change or a business ambiguity. A subagent never decides business behavior; it passes the ambiguity
   to the orchestrator, who asks the user, and pauses the dependent implementation and the tests of the
   expected behavior.
8. **Handover:** changed files, behavior summary, written tests, open points and requested checks.

Run independent tasks in parallel within the available slots. Start a dependent task only with the
needed contract or the result of the previous one. Give a shared file to one owner or sequence the
changes. If the assignment changes, inform the affected subagents and stop superseded work.

## Takeover

The main agent reads the diff and evaluates the completion conditions, the links and the compliance
with the rules. It checks especially that the weaker model stayed within scope; its claim "done" is not
enough. It unifies the shared parts, resolves conflicts and schedules the requested checks into a
suitable verification block. A subagent reports written tests as written; their passing run is
evidenced only by the main agent's result.
