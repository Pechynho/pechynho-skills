---
name: playwright-testing
description: Click-through and visual verification of features or changes in the dev environment with headless Playwright scenario scripts run and tracked by the browser tool, written and judged by tester subagents per group of scenarios, without verifiers. Use on a request for browser testing or a UI/UX check; findings are presented or handed to programming.
---

# Playwright testing

Verify the real use of a feature, its functional scenarios and its look on small and large screens.
**Scenario scripts drive the browser; the [browser tool](shared/browser-tool.md) runs them in a limited
number of headless browsers and keeps the state of the pass.** Tester subagents write the scripts of a
group of scenarios and judge the screenshots, without separate verifiers. The main agent runs the
pass, triages the failures and processes the results; no synthesizing subagent is needed.

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

## 2. Scenarios, groups and the testing folder

The pass lives in a testing folder kept by the [browser tool](shared/browser-tool.md),
`{work_dir}/playwright/{scope}/`. Before `init`, check whether the folder of this scope already exists.
If it does, the pass was interrupted: resume it instead of starting over. Start from `status`, which
also returns the scenarios of a dead run to the queue and kills its leftover browsers; release lost
subagent runs with `release … --lost`, then continue with `next`.

The main agent hands over the scenarios **or explicitly assigns deriving them from the changes**. When
deriving, the tester goes through the diff, the needed surrounding code, the assignment, the
specification and the decisions, and builds the scenario overview per the
[coverage rules](references/scenarios.md). One shared list is built once, by the main agent or by one
tester, so that others do not repeat the preparation; the main agent checks the coverage before a large
pass without requiring further user approval of a clear assignment. Load it with `scenarios FILE`.

Split the scenarios into **groups** by screen or flow. A group owns its test data, so mutating scenarios
of different groups do not collide; the tool runs one group's scenarios in order and different groups in
parallel. Mark each scenario `functional`, `visual` or `both`.

The pass is made of units of work per [number of runs](shared/delegation.md#number-of-runs):

- **Script authoring:** one unit is a group, or several small groups that share screens, whose scripts
  fit one run. A small pass is one unit; then one tester writes, runs and judges everything.
- **Runs** need no subagent: the tool runs the scripts in at most
  [`max_parallel_browsers`](shared/project-context.md#max-parallel-browsers) headless browsers and
  sequences the rest.
- **Triage** of failures is done by the main agent from `result` and the failure screenshot; a failure it
  cannot explain goes to the script's author or to one triage run.
- **Visual judgment:** one unit is the pending screenshots of related screens that one run can view;
  with a substantial visual scope it is separate from script authoring.
- **Exploration** through interactive MCP is optional, one bounded run (see step 6).

Record each subagent run with `assign` and close it with `release`. Hand over the scope, URLs, revision,
roles, existing decisions, the [ground rules](shared/ground-rules.md) and the concrete project rule
files, the testing folder and the tool command, the scenarios or groups, ownership of data, the fix
mode and the results format. Model choice follows [delegation](shared/delegation.md): script authoring,
exploration and visual judgment go to the stronger model. The visual judge must be able to view
screenshots, not only list them; without that ability do not mark the look as verified.

## 3. Environment and test data

Use **Playwright in headless mode**, without opening windows on the user's desktop, including windows
from WSL in Windows. The scenario scripts of the browser tool always run headless. Before the first
interactive navigation check the configuration of the tool used: start Playwright MCP with `--headless`,
set `headless: true` in own one-off scripts. Loading the skill does not change
the configuration of an MCP server already running. If the available tool does not support headless
mode, use an available headless alternative; open a visible window only by agreement with the user.
Verify the look by taking and actually viewing screenshots at the required viewport sizes; headless mode
neither replaces nor prevents this check. Pass this rule to the testers.

The scripts need Node 18+ and Playwright with its browser. `init --playwright` points the tool at the
project's installation; when the project has none, installing Playwright into the testing folder is a
package installation and needs the user's consent per the
[ground rules](shared/ground-rules.md#git-and-package-installation). Without Node or Playwright the pass
falls back to a headless interactive tool, with the same folder and statuses kept by hand.

Before the first write verify **the target URL and the actual database of the application** from
non-sensitive environment or connection information. An account name or the look of a page is not
proof of the dev environment. Creating, changing and deleting test data is allowed **exclusively in the
dev DB**; non-dev environments (staging, beta, production) and the automated-tests database are not
targets of this skill. If the
environment cannot be determined, writes wait.

Load the project's [dev environment](shared/project-context.md#dev-environment) information: how to
reach the app, the test accounts and roles, and how to prepare data. One-off scripts, SQL and clicking through
Playwright are all possible as needed. Prefer application services or the UI for states that depend on
events and invariants. With SQL knowingly handle the bypassed behavior and caches; do not report a bug
created by inconsistent fixtures as a product bug.

Use recognizable test accounts and record the created data with `log data`. Before a larger
intervention back up per the project rules and record the restore. Scripts, results and one-off helpers
live in the testing folder in the [work directory](shared/project-context.md#work-directory).
For worktrees and shared services follow the resolved
[dev environment](shared/project-context.md#dev-environment).

Each group has its own accounts or records for mutating scenarios; inside a group the scenarios run in
ID order, so a later one may read a state an earlier one prepared. Over a single shared MCP session
explore sequentially. Do not manipulate the user's live tabs. The dev
application may have external integrations: for payments and messages use the test mode and local
capture (e.g. Mailpit); click-through testing is no permission for a real payment or a message to a
real recipient.

## 4. Scripts and runs

Playwright is driven by scenario scripts, not by an agent clicking through the pass: a run returns a
few lines instead of page snapshots, and the same scripts serve the retest after fixes. Write one
script per scenario in `scenarios/{ID}.mjs` with the harness of the
[browser tool](shared/browser-tool.md#scenario-scripts); it records the steps, checks, console and page
errors, failed requests, layout hints and screenshots.
Take selectors from the source first; use interactive MCP only briefly, for what the source does not
answer. Each script prepares or restores the data it needs, so that a mutating scenario runs again.

Check functional success the way a user sees it and then where it lasts: after a reload, on the
follow-up screen or by reading the dev DB; a toast alone is not enough. A visual scenario calls `shot`
in each state to judge; the harness takes it at every viewport of the scenario without repeating it,
or in a fresh mobile context per viewport with `perViewport` when the application detects the device.

The author runs each new script with `run ID`, fixes what is the script's fault and confirms it with
`ready`. A script that cannot be written (an unsupported interaction, a missing tool) is set
`unverified` with the reason rather than left pending. Then the main agent runs the pass with
`run --todo` and reads the compact lines; it does not open the result files of passed scenarios. A pass
that may outlast the shell's command timeout runs as a background command or group by group.

For each failing scenario read `result ID` and, when needed, its failure screenshot, and record
`triage`: an application bug (`app`, with a finding), a script bug (`script`, back to its author), an
environment problem (`env`, blocked) or an unstable result (`flaky`, after `run ID --repeat 3`). Tell
the bug of the application from the environment and the test script; do not report a bug created by
inconsistent fixtures as a product bug. Do not fix application code during the pass. Unclear product
behavior goes to the main agent, who follows the
[business questions procedure](shared/business-questions.md); a dependent fix waits for the answer.

Assigned testers may run their scenario scripts through the tool and use the browser for exploration and
diagnosis; everything else in [verification](shared/ground-rules.md#verification) stays with the main
agent, and a click-through script is no reason to run the whole existing Playwright test suite.

## 5. Visual judgment

The judge lists `shots --pending`, actually views each screenshot at its size and judges it per the
[UI/UX checklist](references/scenarios.md#uiux-and-look) with `judge`. The layout hints (overflow,
broken images, clipped text) point to places to look at; they are neither a verdict nor a replacement for
viewing. A screenshot identical to its last judged one keeps its judgment, so a retest needs only the
changed ones viewed, with the `.diff.png` showing what changed. An issue gets a finding or a note.

## 6. Exploration

When the scope has risky or poorly specified parts, one bounded exploration run may drive the browser
interactively through headless MCP outside the scripts. Agree its budget (the screens and the time or
number of steps) in the brief. It records what it tried with `log explore`; a relevant discovery
becomes a new scenario with a script, so that it is repeatable. Interactive MCP is otherwise only for
finding selectors and diagnosing a failure.

## 7. Results and optional fixes

The tester hands over the results per the [output format](references/results.md); the state of the
scenarios, screenshots and findings is in the testing folder. The main agent merges duplicate findings
and keeps the reproduction steps and the different impacts. It separates evidenced bugs from visual
recommendations, open questions and environment limitations.

In presentation mode present the findings and the coverage overview from `status` and `findings`. In fix
mode, after the pass hand the evidenced problems, reproduction, expected behavior, proposed solutions
and user decisions to [programming](../programming/SKILL.md). Include optional visual changes only when
they are in the permitted scope. Do not make fixes waiting on a business decision from the
recommendation alone.

After fixes the main agent runs the affected scenarios with `run --failed` or by their IDs, plus the
scenarios on the same screens, and `run --todo` for results from other code; it marks a finding
`fixed` when the fix lands and `verified` when its scenarios pass. Changed screenshots go to a new short
judging run; do not resume the original tester, do not repeat the whole pass without reason and do not
extend testing endlessly. Done means `next` shows nothing open in the agreed scope; blocked and
unverified scenarios stay explicitly listed.

## 8. Cleanup

The tool closes the browser of each scenario run and kills what a timed-out or crashed run left behind.
Whoever drives a browser outside it (exploration, diagnosis, own one-off scripts) closes its contexts
and browser on completion and on error, ideally in `finally`, per the
[browser cleanup rule](shared/ground-rules.md#browser-cleanup); after checking the processes
terminate only your own leftovers, not the user's browser. Do not leave a browser running between
finished passes. Revert temporary global settings and time travel; coordinate needed caches and
restarts per the project rules. In the summary state which dev data remained for the user's own
click-through and how to find or remove it.
