# Business questions belong to the user

Use this procedure whenever a review, a proposed fix or any other work requires a decision about product
behavior that is not determined by the assignment, the conversation, the specification or the closed
decisions. It applies in every phase: review, verification, synthesis, implementation, planning and testing.

## First check whether the answer already exists

Check the assignment and the related decisions. Respect an explicit user exception. Do not reopen a
closed question only because of a reviewer's preference. When rules conflict and the conflict cannot be
resolved from the assignment and the validity of the decisions, describe the conflict and let the user
decide. The current behavior of the code is not evidence that it is the desired behavior.

## Handover and wording

A subagent passes the question to the main agent together with the related findings. The main agent
merges identical questions and asks the user **with the available question tool**. Use whatever tool
the current environment and mode provide (see [tools](project-context.md#tools)). Only when no such tool is
available, ask directly in the conversation and explain the limitation.

Formulate each question separately and clearly:

1. What needs to be decided and why the assignment does not determine it, in plain words, without
   internal class names.
2. A short concrete example when it helps to explain the difference.
3. A few meaningful options, usually 2–3, with the practical consequence of each.
4. One option marked **Recommended**, ideally the first, with a short reason.

The recommendation follows the known product goals; it is not a decision on the user's behalf. Do not
overwhelm the user with implementation details or with variants the approved rules already exclude.
Keep the technical background with the findings. Related questions may go in one batch, but do not
merge separate decisions.

### Example question

"It is not determined whether an export in progress should include records added after it started.
For example, you start the export at 10:00 and a new member joins at 10:01. Should they be in the file?

- **State at start (Recommended):** the new member will not be in the export. The result matches one
  moment in time and the counts do not change during the export.
- **Include newer records too:** the new member may appear if the export still manages to load them;
  the result will depend on the processing order."

This is only a pattern for a question, not a project decision about exports.

## Waiting and the answer

- Give the question an ID and mark the findings and fixes that depend on it.
- In asynchronous mode continue with independent work and wait for a real answer. Timeout, a default
  choice and the Recommended mark are not consent.
- Keep a dependent finding as a question or "undecidable". Do not write the dependent fix and do not
  mark that part of the review as closed. An interim synthesis with open points may be presented
  before the answer.
- Record the answer with the question, pass it to the affected reviewers, verifiers and the synthesis,
  and re-evaluate the conclusions that depended on it. New or changed findings must pass verification.
- If the user postpones the decision, leave the point open and finish only the independent part.
- In fix mode pass the decisions to `programming`. Writing the decision into the permanent project
  documentation belongs to the permitted scope of that phase; do not create a second conflicting
  version of a rule.
