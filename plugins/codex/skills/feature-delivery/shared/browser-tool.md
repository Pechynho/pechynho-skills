# Browser tool

`browser.py` next to this document keeps the state of one click-through pass in its folder,
`{work_dir}/playwright/{scope}/`, and runs its scenario scripts: which scenarios exist, whose script is
written and confirmed, what each run found on which code state, which failures are triaged, which
screenshots are judged and which findings came out of it. Use it for every pass, small or large; a small
pass is a few scenarios in one group. Prefer it to driving the browser by hand and to tracking results
in your head; it saves context, limits the browsers and survives an interrupted session.

Run it from anywhere with the path of the testing folder (Python 3.8+, standard library only; the
scenario scripts need Node 18+ and Playwright):

```bash
python3 <skill directory>/shared/browser.py {work_dir}/playwright/{scope} <command>
```

## Folder

| Path | Content |
|---|---|
| `testing.json` | Live state: settings, revision, scenarios with their last run, outcome, triage and screenshots, findings, assignments and runs. |
| `log.jsonl` | Append-only history of every change and of recorded checks, decisions, explorations and created data. |
| `harness.mjs` | The [harness](browser-harness.mjs) the scripts import, copied by `init`; `harness` refreshes it. |
| `scenarios/{ID}.mjs` | One script per scenario, named by its ID. |
| `results/{ID}/{run}/` | One run: `result.json`, `output.log`, `pids.json`, `failure.png` and `shots/` with the screenshots and their `.diff.png`. |
| `findings/{ID}.md` | One finding in the [results format](../../playwright-testing/references/results.md#finding). |

A **scenario** belongs to a **group**, a screen or flow whose test data it owns. Its kind is
`functional`, `visual` or `both`. Its script is `pending` (no file), `written` (the file exists, or changed
since it was confirmed) or `ready` (its author ran it and confirmed it with `ready`). Its **outcome** is
`pending`, `passed`, `failing` (the last run failed and waits for triage), `failed` (an application
bug), `blocked`, `unverified` or `flaky`. A **screenshot** is keyed `name@viewport` and is `pending`,
`ok` or `issue`. `status` reports a visual scenario whose run passed as `failed` while one of its current
screenshots is judged an issue and as `pending` while one waits for a judgment.

## Scenario scripts

```js
import { run } from '../harness.mjs';

await run(async ({ page, url, step, check, shot }) => {
  await step('open the order list', () => page.goto(url('/orders')));
  await step('add an order', () => page.getByRole('button', { name: 'Add' }).click());
  await check('the new order is listed', page.getByText('New order'));
  await page.reload();
  await check('the order survives a reload', page.getByText('New order'));
  await shot('order-list');
}, { prepare: async () => { /* create or reset the scenario's own data */ } });
```

- `step(name, fn)` names a part of the scenario for the result; `check(name, locator | fn | value,
  { state, timeout, soft })` waits for a locator, also one a function returns (visible by default), or
  requires a truthy value, and stops the scenario on failure unless `soft`; `check.equal(name, actual,
  expected)` compares values.
- `shot(name, { viewports, fullPage, mask })` takes one screenshot per viewport of the scenario by
  resizing the page in place, so the scenario is not repeated per viewport, and attaches layout hints
  found in the page: horizontal overflow, broken images and clipped text with the elements causing them.
  Resizing changes only the width and height. For an application that detects the device on load or on
  the server, use `perViewport: true`: the scenario runs once per viewport in a fresh context, and a
  viewport marked `mobile` gets touch, a mobile user agent and mobile emulation.
- Every run also records console errors, uncaught page errors, HTTP responses from 400 up and failed
  requests; uncaught page errors, console errors and 5xx responses fail the scenario unless the options
  allow them (`allowConsole: [/regex/]`, `allowStatus: [503]`). A failure leaves `failure.png` and the URL.
- Options: `prepare` and `cleanup` around the browser part (cleanup also runs after a failure),
  `context` (Playwright context options such as `storageState`, `locale` or `colorScheme`),
  `timeout` (action timeout, 10 s by default) and `perViewport`. The script gets `page`, `context`, `browser`, `url(path)`,
  `note(text)` and `out` (its run folder) for anything else it needs.

Selectors come from the source first (templates, components, translations); a short look through
Playwright MCP is for what the source does not answer. A script restores or creates the data it needs
in `prepare`, so that it runs again after a fix.

## Commands

| Command | Use |
|---|---|
| `init --scope S --url URL [--repo DIR \| --no-repo] [--head REF] [--base REF] [--working-tree] [--max-browsers N] [--timeout SEC] [--viewport NAME=WxH[:mobile] …] [--playwright DIR …] [--browser B]` | Create the folder for the verified dev URL. The tested repository is the one of the current directory unless `--repo` names it; `init` refuses without one unless `--no-repo`. `--max-browsers` takes [`max_parallel_browsers`](project-context.md#max-parallel-browsers); the first viewport is the primary one (desktop 1440x900 and mobile 390x844, marked mobile, by default); `--playwright` names directories to resolve Playwright from (the project root when it has Playwright, otherwise a folder where it was installed). |
| `config [--url …] [--max-browsers N] [--timeout SEC] [--viewport …] [--playwright …] [--diff-threshold F] [--diff-tolerance N]` | Change a setting; without options print them. Refuses to drop a viewport a scenario names. |
| `scenarios FILE` / `scenario ID --title T --group G [--kind K] [--priority P] [--role R] [--viewports V …] [--data D]` | Load the scenario list (a JSON list of objects with the same keys) or add and change one. Without `--viewports` a functional scenario uses the primary viewport and a visual one all of them, resolved from the settings at each run. |
| `run ID … \| --group G \| --todo \| --failed \| --all [--repeat N] [--wait SEC]` | Run scripts in headless browsers: scenarios of one group in ID order, groups in parallel up to `max_browsers`, counted across every process working on the folder. Each run has a timeout; the tool kills what is left of its node process and browser. Prints one compact line per scenario. `--todo` runs ready scripts not run yet or run on other code, `--failed` the failing, failed and flaky ones, `--repeat` checks instability. `--wait` limits the time spent waiting for browsers held by other processes (a subagent's run uses it): after it the run starts nothing more and refuses as `busy`; the scenarios it did not start or whose `--repeat` it could not finish keep their previous outcome, and what it finished is recorded. A pass that may outlast the command timeout of the agent's shell runs as a background command, or group by group; a run killed from outside loses the results of its unfinished scenarios, and `status` returns them to the queue. |
| `ready ID …` | The author confirms a script: its current version completed a run (passed or failed, not crashed). Changing the file later makes it `written` again. |
| `result ID` | The last run in a few lines: failed steps and checks, the error, console and page errors, 5xx responses, the failure screenshot and the folder. Enough for triage without opening `result.json`. |
| `triage ID app\|script\|env\|flaky [--finding F] [--note N]` | The cause of a failing run: `app` makes it `failed` (attach the finding), `script` returns the script to its author, `env` makes it `blocked`, `flaky` marks it unstable; `env` and `flaky` need the evidence in `--note`. |
| `set ID pending\|blocked\|unverified --reason R` | Set an outcome by hand, for example a scenario that cannot be scripted. |
| `shots [ID …] [--group G] [--pending]` | Screenshots with their absolute paths, judgment, layout hints and the difference from the last judged screenshot of the same key. |
| `judge ID ok\|issue [--shots KEY …] [--finding F] [--note N]` | Record the judgment of the viewed screenshots (all pending ones of the scenario by default); an issue needs a finding or a note. |
| `finding ID --scenarios S … --kind K --title T [--severity S]` / `resolve ID STATUS --reason R [--duplicate-of ID]` / `findings [--all]` | Index a finding after writing `findings/{ID}.md`; statuses `open`, `awaiting_decision`, `fixed`, `verified`, `rejected`, `duplicate`. |
| `assign --owner T2 --task script\|triage\|visual\|explore [ID …] [--group G]` / `release T2 [--lost]` | Record which subagent run owns which scenarios; `--lost` for a run that ended without a result. |
| `next` | What to do now: scripts to write or finish, scenarios to run or run again after a code change, failures to triage, screenshots to judge, fixed findings whose scenarios pass. |
| `status` | Overview: settings, code state now and at `init`, scripts, outcomes, screenshots, results from other code, running scenarios and assignments, findings. Start here after an interruption; it also returns the scenarios of a dead run to the queue and kills its leftovers. |
| `validate` | Check the state, scripts, screenshots, findings and the log. Exit code 1 on an error. |
| `log check\|decision\|note\|explore\|data key=value …` | Append a record, for example `log data text="order #123 for tester@example.com"`. |

**Screenshot differences.** Each run compares a screenshot with the last judged screenshot of the same
key inside the browser, also when newer runs were not judged in between, and writes a `.diff.png` with
the changed pixels in red. A screenshot that does not differ keeps the judgment, so a retest needs only the changed ones viewed. By default any pixel
beyond a per-channel tolerance of 24 counts; raise `--diff-threshold` (a share of the pixels) only for
a page with known noise, and mask dynamic content in `shot` rather than tolerating it.

**Code state.** Each run records HEAD plus a hash of the uncommitted changes. `status` and `next` list
results from another code state, and `run --todo` runs them again; the agent decides which really need
it.

The tool records and runs, it does not judge: the scenarios, whether a script checks the right thing,
the cause of a failure, the look of a screenshot and whether a finding holds stay the agent's
decisions. Without Python or Node keep the same folder and rules by hand and drive the browser through
the available headless tool.
