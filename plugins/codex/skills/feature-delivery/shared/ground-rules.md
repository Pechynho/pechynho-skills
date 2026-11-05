# Ground rules

These rules apply inside every skill of this collection. The skills rely on them and do not repeat
them. Every skill carries the same copy of the `shared/` files; read each of them once per session, not
again under another skill's path, unless the context was summarized since. The project's own
instructions (see [project context](project-context.md)) apply on top of them: a project rule that is
stricter wins; a project rule that relaxes one of these rules applies only when it says so explicitly.

## Language

- Program in English and write code comments in English, unless the project says otherwise.
- Communicate between agents in English, whatever language the user uses: subagent briefs, messages
  between agents, subagent results and handovers, plans, review findings, test results and handoff
  documents. Only the communication with the user follows the user's language; quote the user's
  decisions in English and keep only product terms that have no English equivalent.
- Write only the comments that explain hard-to-understand parts of the code or a deliberate,
  non-obvious choice.
- Keep the code, its comments, tests and names free of references to workflow documents: no task,
  question, decision, finding or feedback IDs (`T-001`, `Q-002`, `D-003`, `R3-01`, `FB-001`) and no
  paths to plans, reviews or handoffs. These documents may not be in the repository and may be
  deleted; write the reason itself into the comment instead.

## Git and package installation

- Never run `git commit`, `git push` or any other git operation that changes history or the remote
  without an explicit instruction. When you think it is time to commit, ask. The same applies to
  installing packages: ask as well.
- An explicit assignment of the whole [feature-delivery](../../feature-delivery/SKILL.md) workflow
  authorizes ongoing local commits of that work within its confirmed scope, unless the user says
  otherwise. Creating, editing or loading the skill does not grant this permission. Push, history
  changes, package installation and other separately approved actions are not authorized by it.
- Never add a static-analysis ignore, a lint suppression or a baseline entry on your own; ask first.

## Verification

- **Linters, formatters, static analysis, typecheck, tests and builds are run exclusively by the main
  agent.** Subagents do not run these tools, not even on a single file. They may write tests, check code
  by reading and hand over a request for a specific check.
- **Exception for requested browser click-through testing:** testers assigned under
  [playwright-testing](../../playwright-testing/SKILL.md) may drive a browser, run their scenario
  scripts through the browser tool and run one-off browser scripts. Automated test suites, linters,
  static analysis, formatters and builds remain exclusive to the main agent.
- Run the project checks only at the moments the [check timing](#check-timing) sets. By default these
  are milestones: after a larger coherent part of the work (several tasks, not a single handover),
  before a checkpoint commit, a click-through or a review, and before the handover. Choose the relevant
  tools and scope by the change; do not run them after every small edit or task.
- Outside these runs run only a targeted check, and only when debugging a concrete failure or when the
  next step depends on its result (generated code, a migration). After a late small change run the
  targeted checks of what it affects; the full checks run once before the handover.
- The check timing decides when checks run, never a subagent's cache: do not run checks early to catch
  a subagent while it lives. A failure goes with the failing cases and the diff back to its author when
  that is still within minutes of its handover, otherwise to a new short run.
- Run a check that takes minutes as a background command and process the handovers of other runs
  meanwhile; read only its summary and failures, per
  [working with tool output](#working-with-tool-output).
- The main agent coordinates subagents' requests, merges identical checks and passes the results back.
  When debugging a specific failure, use a targeted run instead of repeating the whole suite.
- Before finishing, satisfy the project's checks (see [project context](project-context.md#checks)),
  unless the [check timing](#check-timing) is `never`.
  For a documentation-only change verify the documentation.
- **Do not repeat a successful check without a subsequent change.** Report the run already performed,
  its result and any limitations.

## Check timing

Work with more than one milestone runs in one of three modes. Work verified by a single run of the
checks has nothing to decide, unless the user asks for `never`.

- `milestones`, the default: the checks run at milestones per [Verification](#verification), so an
  error shows up close to its cause and does not spread into later work.
- `at_end`: the whole implementation including its tests is written and integrated first; only then do
  the project checks run and their failures get fixed. Reading and integrating each handover stays as
  it is, and the targeted checks of [Verification](#verification) stay allowed. Checkpoint commits
  before that run record that the checks are still pending. The main agent keeps the subagents' check
  requests for that run, in the plan log when there is a plan.
- `never`: the user takes over the checks, for example in CI, and the agent runs no linters,
  formatters, static analysis or test suites in any phase. Tests are still written, and a build or
  generation step that the next step depends on stays allowed. Nothing counts as verified by these
  checks: the project's requirement stays open for the user, and the handover says so and lists the
  checks to run, including the subagents' requests.

Recommend `milestones` or `at_end` for the concrete work:

- `at_end` when intermediate states cannot pass anyway (a refactoring, a rename or an API change across
  layers), when the checks are slow compared with the work, or when the tasks are independent and
  follow settled contracts and known patterns.
- `milestones` when later work builds on earlier results (a new shared contract, data model or
  pattern), for risky logic or code with little test coverage, when the work spans several sessions,
  or when a commit hook runs the checks and checkpoint commits are expected.

The user decides, although this is a technical choice. Ask with the question tool before the
implementation starts, with the recommended mode first and the reason drawn from the work at hand.
Offer `never` as the last option and do not recommend it; only the user's explicit choice sets it.
Do not ask when the assignment, an earlier answer or the plan progress (`check_timing`) already settles
it. Record the answer in the plan progress when there is a plan and pass it on in a handover. The user
may change the mode at any time; when the work turns out differently than expected, recommend the
change.

## Implementation and tests order

- **Write tests directly as part of the feature or change**, unless the user says otherwise. Do not wait
  for click-through testing or a further approval of the implementation.
- Use the testing tools and procedures the project already uses for the given layer. If the project does
  not test a layer, do not add tests for it or introduce a new framework because of a change.
- A subagent may write tests too; running them is controlled exclusively by the main agent per
  [Verification](#verification).

## Reuse, DRY and abstractions

- Before copying code, configuration, templates or test setup, look for an existing shared solution
  and consider extracting the repeated rule into one place.
- Share code that represents the same rule and changes for the same reason. Similar-looking code
  with different responsibilities need not become one abstraction; keep extraction within the task's
  scope.
- Introduce a design pattern when a concrete need in the task calls for it, for example a strategy for
  several interchangeable variants, an adapter or facade to isolate an external API, a builder for
  a complex construction. Prefer the patterns the project already uses. Do not add an abstraction for
  a single implementation or a hypothetical future case.

## Translations

- When the project translates its UI, add every new translation key to all locales the project
  supports right away; do not leave a key in one language for someone to fill in later.

## Browser cleanup

- Always close the browsers you started (MCP sessions and own scripts) once the verification is done:
  close the context and the browser at the end of a script, ideally in `finally`. Do not leave them
  running between steps or after the task. Finally check that none of yours is left hanging
  (for example `pgrep -af chrom`); never terminate the user's own browser.

## Working with tool output

- Locate places with a search first and read a file once in the needed range instead of many small
  slices. Filter logs and command output with `head`, `tail` or `grep`; do not print whole HTML pages,
  JSON dumps, database rows or build logs into the conversation. Write a large output to a file in the
  [work directory](project-context.md#work-directory) and read the relevant part.
- Save screenshots and other large artifacts as files and open them only when the task needs to judge them.

## Rules for new code

- Older code does not always follow the project's rules. **New code you write must follow them**, unless
  the user allows otherwise.
