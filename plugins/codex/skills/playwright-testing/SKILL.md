---
name: playwright-testing
description: Click-through and visual verification of features or changes with headless Playwright in the dev environment by tester subagents, each with one bounded group of scenarios, without verifiers. Use on a request for browser testing or a UI/UX check; findings are presented or handed to programming.
---

# Playwright testing

Before starting, resolve the [project context](shared/project-context.md) and follow the
[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.

Verify the real use of a feature, its functional scenarios and its look on small and large screens.
Testing is done by **tester subagents, each with one bounded group of scenarios, without separate
verifiers**. The main agent processes the results; no synthesizing subagent is needed.

Use the skill for requested click-through testing; an implementation or a code review by itself is not
consent to launch a browser. On an explicit browser-testing assignment do not ask for further general
permission. An explicit assignment of the whole [feature-delivery](../feature-delivery/SKILL.md)
includes dev click-through and the subsequent fixes in the confirmed scope; take that mode from the
orchestrator without asking again.

## 1. Scope and expected result

From the conversation determine which pages, features or changes to test and whether to only present
the findings or to fix them afterwards via `programming`. Ask about unclear points with the question
tool; do not re-confirm scope or permissions already given. Clarify the fix mode at the start if
possible, at the latest before fixes; an unclear fix mode does not block testing a clearly defined scope.

Determine the Git scope (working tree, branch against its base, or commits) the same way as in
[code review](../code-review/SKILL.md#1-clarify-the-assignment), and capture the revision and the
tested form of the working tree. Verify that the running dev application really contains these changes;
when the code changes during the pass, mark which scenarios need repeating.

## 2. Split of work and scenarios

- **One tester:** a small scope that fits one run. In one pass it checks functionality and UI/UX using
  the same prepared states; it does not repeat a whole scenario just for a screenshot.
- **Several testers:** a larger feature or many scenarios. Split the scenario list into groups by
  screen or flow so that each group fits one run per
  [one assignment per run](shared/delegation.md#one-assignment-per-run); one tester
  owns one group. When the feature has a substantial visual scope, separate the functional pass from
  the UI/UX and responsiveness pass: the functional tester works from the DOM, the responses and the
  dev DB and does not view screenshots, the UI tester takes and views them. The number of testers
  follows the number of groups. Run at most two or three browsers in parallel and sequence the rest;
  assign the test data per group so that mutating scenarios do not collide.

The main agent hands over the scenarios **or explicitly assigns deriving them from the changes**. When
deriving, the tester goes through the diff, the needed surrounding code, the assignment, the
specification and the decisions, and builds the scenario overview per the
[coverage rules](references/scenarios.md). The main agent checks the coverage before a large pass
without requiring further user approval of a clear assignment. With several testers one shared list is
built first, by the main agent or by one tester, so that the others do not repeat the preparation.

Hand over the scope, URLs, revision, roles, existing decisions, the
[ground rules](shared/ground-rules.md) and the concrete project rule files, the scenarios or the task to derive them, ownership of data and browsers,
the fix mode and the results format. Model choice follows
[delegation](shared/delegation.md): exploration and visual judgment go to the
stronger model. The UI tester must be able to view screenshots, not only save them; without that
ability do not mark the look as verified.

## 3. Environment and test data

Use **Playwright in headless mode**, without opening windows on the user's desktop, including windows
from WSL in Windows. Before the first navigation check the configuration of the tool used: start
Playwright MCP with `--headless`, set `headless: true` in own scripts. Loading the skill does not change
the configuration of an MCP server already running. If the available tool does not support headless
mode, use an available headless alternative; open a visible window only by agreement with the user.
Verify the look by taking and actually viewing screenshots at the required viewport sizes; headless mode
neither replaces nor prevents this check. Pass this rule to the testers.

Before the first write verify **the target URL and the actual database of the application** from
non-sensitive environment or connection information. An account name or the look of a page is not
proof of the dev environment. Creating, changing and deleting test data is allowed **exclusively in the
dev DB**; beta, production and the automated-tests database are not targets of this skill. If the
environment cannot be determined, writes wait.

Load the project's [dev environment](shared/project-context.md#dev-environment) information: how to
reach the app, the test accounts and roles, and how to prepare data. One-off scripts, SQL and clicking through
Playwright are all possible as needed. Prefer application services or the UI for states that depend on
events and invariants. With SQL knowingly handle the bypassed behavior and caches; do not report a bug
created by inconsistent fixtures as a product bug.

Use recognizable test accounts and record the created data. Before a larger intervention back up per
the project rules and record the restore. Store one-off scripts and results in the
[work directory](shared/project-context.md#work-directory), for example `{work_dir}/playwright/{scope}/`.
For worktrees and shared services follow the resolved
[dev environment](shared/project-context.md#dev-environment).

With several testers separate the accounts or records for mutating scenarios. Prepare shared states first
and then read them, or sequence the passes. Use separate browser contexts if the tool supports them;
over a single shared MCP session test sequentially. Do not manipulate the user's live tabs. The dev
application may have external integrations: for payments and messages use the test mode and local
capture (e.g. Mailpit); click-through testing is no permission for a real payment or a message to a
real recipient.

## 4. Click-through and visual check

Run the scenarios per the [checklist](references/scenarios.md). Record the results and relevant new
scenarios as you go. Confirm a functional success after a reload, on the follow-up screen or by reading
the dev DB; a toast alone is not enough. Besides the browser interaction check relevant console errors
and network requests. Determine whether it is a bug of the application, the environment or the test script.

Assigned testers may drive Playwright and run one-off browser scripts for this pass; everything else in
[verification](shared/ground-rules.md#verification) stays with the main agent, and a click-through
script is no reason to run the whole existing Playwright test suite.

Run the repeatable scenarios as headless scripts in the working directory, one per scenario and named
by its ID, with a compact output: the ID, passed or failed, the checked facts and the paths of the
evidence. Interactive driving through MCP is for exploration and for diagnosing a failure, not for the
pass itself. Save screenshots as files and open one only when the scenario needs a visual judgment.
The scripts are the basis of the retest after fixes: each one states the command that runs it and
prepares or restores the initial state it expects, so that a mutating scenario runs again; where the
script cannot restore its data, name the preparation step in the results.

Testing subagents do not fix application code during the pass. They try to reproduce a bug again from
the described initial state and mark an unstable one as unstable. No further verification phase runs.
Unclear product behavior goes to the main agent, who follows the
[business questions procedure](shared/business-questions.md); a dependent fix
waits for the answer.

## 5. Results and optional fixes

The tester hands over the results per the [output format](references/results.md). The main agent
merges the outputs of the testers, removes duplicates and keeps the reproduction steps and the
different impacts. It separates evidenced bugs from visual recommendations, open questions and
environment limitations.

In presentation mode present the findings and the coverage overview. In fix mode, after the pass hand
the evidenced problems, reproduction, expected behavior, proposed solutions and user decisions to
[programming](../programming/SKILL.md). Include optional visual changes only when they are in the
permitted scope. Do not make fixes waiting on a business decision from the recommendation alone.

After fixes repeat the affected scenarios and their links in a targeted way: the main agent runs the
saved scripts of the affected IDs and reads their compact results, and a new short tester run judges
the links and, where the fix touched the UI, the look. Do not resume the original tester, do not repeat
the whole pass without reason and do not extend testing endlessly. Done means the overview of relevant
scenarios has real results; blocked and unverified points stay explicitly listed.

## 6. Cleanup

Each tester closes its contexts and browser on completion and on error, ideally in `finally`, per the
[browser cleanup rule](shared/ground-rules.md#browser-cleanup); after checking the processes
terminate only your own leftovers, not the user's browser. Do not leave a browser running between
finished passes. Revert temporary global settings and time travel; coordinate needed caches and
restarts per the project rules. In the summary state which dev data remained for the user's own
click-through and how to find or remove it.
