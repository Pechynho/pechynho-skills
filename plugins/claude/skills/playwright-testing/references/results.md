# Click-through results

The tester keeps the scenarios and findings up to date throughout. The format and the handover via
messages or files are decided by the main agent. The output must not confuse planned steps with
performed verification.

## Scenario overview

For each ID state the actual result:

- **Passed:** the expected result was verified, including the needed persistence and links.
- **Failed:** an evidenced deviation; a link to the finding.
- **Blocked:** a concrete obstacle, for example a missing worker or undecided product behavior.
- **Unverified:** a part not performed and the reason; a tool or time limitation is not a successful result.

For each scenario also state the path of its script, the command that runs it, the preparation or reset
of its data and the path of its evidence, so that the retest can run the script without the tester. Record the environment URL, revision, browser, viewports, roles, languages
and look modes actually used. If the state of the code changed during the work, state which results
relate to which form.

## Finding

- A stable ID, the related scenarios and a short title.
- Kind: functional bug, evidenced UI bug, UX recommendation, question or environment problem.
- Concrete impact and severity; a look preference is not automatically a bug.
- Initial state, role and identification of the test data without unnecessary sensitive details.
- Exact reproduction steps, actual and expected result and the source of the expectation.
- Evidence: the relevant screenshot with viewport, the state after reload, the request response or the
  finding from the dev DB. Do not store session tokens or secrets in the report.
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
