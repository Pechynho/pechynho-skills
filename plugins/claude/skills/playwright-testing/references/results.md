# Click-through results

The state of the scenarios, screenshots and findings lives in the testing folder of the
[browser tool](../shared/browser-tool.md) and is kept up to date throughout; a tester's handover adds
what the tool does not hold. The output must not confuse planned steps with performed verification.

## Scenario overview

For each ID state the actual result:

- **Passed:** the expected result was verified, including the needed persistence and links; for a
  visual scenario also every current screenshot judged.
- **Failed:** an evidenced deviation; a link to the finding.
- **Blocked:** a concrete obstacle, for example a missing worker or undecided product behavior.
- **Unverified:** a part not performed and the reason; a tool or time limitation is not a successful result.
- **Flaky:** passes and fails from the same state; the conditions observed.

`status` of the tool gives the overview, `result ID …` the evidence of the last runs. A script whose data cannot
be restored in its `prepare` names the preparation step in the handover. Record the roles, languages and
look modes actually used; the tool records the URL, code state, browser and viewports. When the code
changed during the work, `status` lists the results from another code state; say which of them were not
run again.

## Finding

- A stable ID, the related scenarios and a short title; the same ID indexes it in the tool.
- Kind: functional bug, evidenced UI bug, UX recommendation, question or environment problem
  (`functional_bug`, `ui_bug`, `ux_recommendation`, `question`, `environment`).
- Concrete impact and severity; a look preference is not automatically a bug.
- Initial state, role and identification of the test data without unnecessary sensitive details.
- Exact reproduction steps, actual and expected result and the source of the expectation.
- Evidence: the run folder of the scenario, the relevant screenshot with viewport, the state after
  reload, the request response or the finding from the dev DB. Do not store session tokens or secrets
  in the report.
- Whether the problem could be repeated; mark an unstable bug and describe the conditions.
- Recommended solution and any uncertainties. A visible symptom is not evidence of a specific cause in
  the code.
- The state after any fix and the scenarios that were re-verified.

The main agent merges duplicates from several passes and keeps the evidence and the different impacts.
Without separate verifiers: the reproduction is done directly by the tester as part of its work. The
synthesis must not turn an unresolved question into a confirmed bug.

## Final handover

Summarize the scope and coverage, the evidenced findings by impact, optional recommendations and open
questions. For fixes add their result and the scenarios actually repeated. State the remaining
limitations, the location of the evidence, the dev data left behind and how to find or remove it.
Confirm the cleanup of your own browser sessions and temporary global settings; admit any cleanup
problems explicitly.
