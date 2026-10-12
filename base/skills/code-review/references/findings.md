# Outputs and evidence

The format is shared by reviewers, verifiers and the synthesis regardless of how the information is
passed. Use brief structured text; files or a particular serialization format are not required.

## Reviewer finding

- **ID and title:** a stable identifier, for example `R2-03`, and the concrete problem.
- **Kind and perspective:** bug, recommendation or question; the review area it belongs to.
- **Location and revision:** file, exact lines or symbol, and the reviewed state of the code.
- **Scenario:** the input and conditions under which the problem shows; current and expected behavior.
- **Evidence:** the concrete code flow, the violated rule with a link, or the result of a performed check.
  The expected behavior must come from the assignment, a rule, a contract or a decision, not from a guess.
- **Impact and severity:** who is affected and with what consequence. Separate the impact from the
  certainty of the claim.
- **Proposed solution:** fix of the cause, affected places, a possible alternative and its drawbacks.
- **Verification of the fix:** the concrete scenario or check that tells correct behavior from the original bug.
- **Uncertainties:** assumptions, missing information and the ID of a related business question.

Bug severity: **critical** (e.g. data loss or a fundamental permission breach), **high** (a fundamental
scenario broken), **medium** (a limited but real wrong result), **low** (a small concrete impact).
Always back it with a scenario. A purely optional improvement must not be presented as a bug.

Every reviewer also hands over the inspected areas, checks and limitations, even without any finding.
It names the concrete files or sections of its assigned scope that remained unchecked so that the
orchestrator can arrange a follow-up; a general statement about a risk-based check is not enough.
It records every bug found in old code or outside the feature with the same evidence and passes it to
verification, marked as an existing problem outside the change; age or unrelatedness to the feature
is no reason to omit a finding.

## Verification

Keep the original finding and add:

- the verifier's ID and the checked revision;
- **confirmed / refuted / undecidable**;
- own evidence and the explanation of the conclusion, including any change of severity;
- an assessment of the proposed fix and its possible side effects;
- the checks performed and their actual results;
- an open question when a decision or more information is needed.

Do not present a proposed test as performed. A recommendation may be verified as technically
beneficial, but it remains a recommendation. On a second assessment keep both conclusions and explain
how a disagreement was resolved.

## Synthesis and handover

For a merged finding keep the original IDs, the cause, all distinct impacts and the needed locations.
The output contains confirmed bugs by severity, separated recommendations, open questions and an
overview of the verification. It includes all confirmed bugs, including existing problems outside the
feature, with their origin marked; the out-of-scope ones are listed separately because fixing them needs
the user's consent. Add the coverage of perspectives and the limitations. Refuted findings
stay traceable with the reason for the refutation.

For incorporation also pass the permitted fix scope (the reviewed scope plus only the out-of-scope
findings the user approved), the user's answers, the dependencies between
findings and the verification requirements. Do not pass an undecided proposal as agreed product behavior.
