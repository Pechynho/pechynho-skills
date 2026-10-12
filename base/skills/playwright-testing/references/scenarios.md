# Scenarios and coverage

The list of scenarios is supplied by the main agent, or the tester is assigned to derive it from the
changes and the requirements. Derived scenarios come from the assignment and the product rules; the code
alone does not determine the expected behavior. Read the surrounding implementation and the follow-up
screens needed to catch regressions, not the whole unrelated product.

## Overview before the pass

Each scenario has an ID, goal, role, initial data and state, steps, expected result and the relevant
viewport. With two testers add the responsible agent. Prioritize the main path, the riskiest changes
and permissions. Scenarios may be extended while exploring; new points must relate to the assignment
and have an explained purpose.

## Functional areas

- The successful pass from entering the feature to the actual save and the follow-up effect.
- Relevant roles and permissions: owner, editor, member, anonymous or unauthorized user by feature;
  access to others' records/groups when the change touches data isolation.
- Required values, invalid inputs, boundaries, empty and filled state, long values and diacritics.
- Create, edit, cancel and delete per the supported workflow; repeated action and double submit.
- Filters, sorting, pagination, opening a detail and returning; reload, Back/Forward and a direct link
  by the change.
- Loading, success, error and recovery. Simulate an outage only in isolation in a test context; do not
  interrupt shared services for it.
- Asynchronous results and related notifications: wait for a concrete state with a reasonable limit,
  not for a randomly long sleep. Without a running worker mark the respective scenario as blocked.
- Persistence after reload and agreement with the follow-up listing or the dev DB; a changed button
  look alone is not enough.

Do not force all combinations. Pick relevant representatives and risky combinations and justify
omissions. Bypassing the UI with a script or SQL during data preparation does not count as a tested
user pass.

## UI/UX and look

Check at least a small mobile and a large desktop unless the feature has a narrower assigned scope.
Choose the sizes by the project (e.g. 390 × 844 and 1440 × 900) and record the actual values. Add an
intermediate width or the surroundings of a breakpoint where the layout changes behavior or a collision
is likely. Do not present responsive emulation as a test on a physical device or in another browser engine.

- Readability, wrapping and overflow of texts, unwanted horizontal scroll and clipped controls.
- Long names and translations, large numbers, missing images, many items and empty content.
- Modals, dropdowns, tooltips and overlays; visibility of actions also when scrolling or with a small
  window height.
- Consistency of the project components, spacing, hierarchy and responsive rules, including
  intentional full bleed.
- Loading, disabled, validation, error and success states; understandable feedback and a way forward.
- Keyboard, visible focus, its order and return after closing a modal, labels of icon buttons,
  availability of important actions without hover and usability of touch targets.
- Light and dark mode where the part supports them; relevant languages including long translations.

Use screenshots and actually view them. The DOM and element geometry help diagnosis, but by themselves
they are not enough to conclude that the UI looks right. A keyboard and look check is not a full
accessibility audit; do not report a screen-reader verification that was not performed.

## When to stop

After the pass every relevant scenario has the status passed, failed, blocked or unverified. Stop after
covering the agreed scope and the targeted verification of fixes; do not extend it into unlimited
testing of the whole application. If new findings point to a bigger problem outside the scope, describe
it to the main agent.
