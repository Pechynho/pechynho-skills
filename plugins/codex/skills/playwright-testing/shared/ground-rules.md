# Ground rules

These rules apply inside every skill of this collection. The skills rely on them and do not repeat
them. The project's own instructions (see [project context](project-context.md)) apply on top of them:
a project rule that is stricter wins; a project rule that relaxes one of these rules applies only when
it says so explicitly.

## Language

- Program in English and write code comments in English, unless the project says otherwise.
- Communicate between agents in English, whatever language the user uses: subagent briefs, messages
  between agents, subagent results and handovers, plans, review findings, test results and handoff
  documents. Only the communication with the user follows the user's language; quote the user's
  decisions in English and keep only product terms that have no English equivalent.
- Write only the comments that explain hard-to-understand parts of the code or a deliberate,
  non-obvious choice.

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
  [playwright-testing](../../playwright-testing/SKILL.md) may drive a browser and run one-off browser
  scripts. Automated test suites, linters, static analysis, formatters and builds remain exclusive to
  the main agent.
- Run checks after finishing the work or a larger coherent part. Choose the relevant tools and scope by
  the change; do not run them after every small edit.
- The main agent coordinates subagents' requests, merges identical checks and passes the results back.
  When debugging a specific failure, use a targeted run instead of repeating the whole suite.
- Before finishing, satisfy the project's checks (see [project context](project-context.md#checks)).
  For a documentation-only change verify the documentation.
- **Do not repeat a successful check without a subsequent change.** Report the run already performed,
  its result and any limitations.

## Implementation and tests order

- **Write tests directly as part of the feature or change**, unless the user says otherwise. Do not wait
  for click-through testing or a further approval of the implementation.
- Use the testing tools and procedures the project already uses for the given layer. If the project does
  not test a layer, do not add tests for it or introduce a new framework because of a change.
- A subagent may write tests too; running them is controlled exclusively by the main agent per
  [Verification](#verification).

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
