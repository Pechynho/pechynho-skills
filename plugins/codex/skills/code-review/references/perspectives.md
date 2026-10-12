# Perspectives and split of work

The orchestrator goes through this overview before splitting the review. A reviewer reads its assigned
perspectives and the related project rules. The boundaries help to split responsibility; a finding that
spans several areas has one ID and several labels.

| Perspective | What to verify |
|---|---|
| Correctness and regressions | Logic, boundaries, null and empty values, error branches, compatibility of callers and impact on existing scenarios. |
| Security and privacy | Server-side permissions, group isolation, untrusted inputs, sessions, secrets, data leaks and personal data in logging. |
| Product and business | Compliance with the assignment, the specification and closed decisions; completeness of scenarios, prices, states and consistent meaning of terms. |
| Architecture, maintainability and DRY | Responsibilities, module boundaries, dependencies, suitable patterns, duplicated rules and the risk of an unsuitable shared abstraction. |
| Project rules and idiomatic code | Concrete project rules, typing and the suitable features of the used versions of the language, framework and tools. |
| Existing solutions and unnecessary complexity | Available services, components, the standard library, the framework and packages; own implementations and workarounds without justification. |
| Performance and resources | N+1, indexes, size of queries and responses, cache and invalidation, memory, long requests, rendering and releasing resources. |
| Data, concurrency and asynchronous processing | Transactions, consistency, concurrent changes, idempotence, retry, event order, migrations, serialization and message compatibility. |
| Testability and risk coverage | Essential scenarios, quality of assertions, falsely green tests, determinism, isolation and a testable interface. |
| UX and accessibility | Keyboard, focus, mobile, loading/error/empty states, translations, feedback and understandable controls. |
| Operations and diagnostics | Deployment, concurrent versions, configuration, worker restarts, rollback, logs and the ability to notice and trace an error. |

## How to combine perspectives

For a smaller change, correctness may be combined with testability, security with data isolation,
architecture with existing solutions, or performance with operations. For a complex change separate
data/concurrency and product from general correctness. Omit UX for a change without impact on the user
interface; note every omission in the coverage. No relevant area may disappear just because X is
smaller than the number of perspectives.

For a supplementary check of a specific module or scenario per the
[split rules](../SKILL.md#2-split-the-perspectives-among-review-subagents), keep the whole change
including that module in the scope of the cross-cutting reviewers. They thus also check the links
between modules, duplicates and the consistency of shared rules.

## Modern features and standards

First find the actually supported versions from the project configuration, lockfile and runtime
requirements; a version you remember from elsewhere is an example, not an assumption. Do the same for
every language, framework, template engine and tool involved; for configuration formats check the capabilities of the specific parser and configuration schema.

Suggest current features when they bring clearer code, stronger type checking, lower risk or better
performance. Explain the concrete benefit and compatibility. Newer syntax by itself does not make the
older form a bug. Do not force a dependency upgrade or a change of the supported runtime outside the
assignment. Verify an unclear or version-sensitive claim in the official documentation for that
version; do not present an uncertain claim as a violation of a standard.

## Abstractions and existing tools

Apply the shared [reuse and DRY rules](../shared/ground-rules.md#reuse-and-dry). Propose a design
pattern for a concrete problem; do not demand it just because it exists.

Look for a solution first in the project, then in the standard library, the framework and the already
installed packages. Recommend a new dependency only with a benefit, compatibility and maintenance cost.
The review installs no packages. For a workaround check whether it addresses a real limitation, and
respect closed technical decisions.

## Tests and user checks

Judge the quality of the existing tests and describe the risky scenarios. Tests are written together
with the change, unless the user says otherwise, and only for layers the project already tests. Judge
missing coverage by the concrete risk; do not demand a new testing framework. Review agents do not fix
or run tests; a browser launch follows the separate project rules.
