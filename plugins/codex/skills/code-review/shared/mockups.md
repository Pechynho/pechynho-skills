# Mockups

A mockup shows the user what a visual result will look like before it is built. Once approved, it
guides the implementation of the look. [Planning](../../planning/SKILL.md) offers mockups at the end
of the plan, [programming](../../programming/SKILL.md) before a large visual step that has none.

## When to offer them

Offer mockups only for a result the user sees: a new screen or dashboard, a substantially redesigned
page, a larger component, an e-mail or a printed document. Do not offer them for a change without a
visual result or for a small adjustment of an existing screen, and do not ask again about a step that
already has an approved mockup or for which the user declined them.

Ask with the question tool whether to make them and in what scope, in one batch, for example:

- **Key screens (Recommended):** one mockup per main screen, in its default state.
- **Screens and states:** also the empty, loading, error and permission states and the narrow layout.
- **One screen:** only the screen named by the user, as a quick illustration.

With a plan, record the answer as a decision, a refusal and the screens left out included, so that
programming does not ask about the same screens again.

## Variants and approval

1. For each main screen prepare 2–3 variants of its default state that differ in the layout or the
   visual approach, not only in colors, and show them together so the user can compare them (side by
   side or switchable on one page). Name the trade-off of each in one line. Skip the variants when the
   user already describes the direction or asked for one quick screen, and start with a single mockup.
2. The user picks a variant or combines several. Rework the chosen one into a single mockup per screen
   and add the states agreed in the scope.
3. Ask the user to approve it. Approval is an explicit answer; silence, a timeout or the Recommended
   mark is not approval. Visual feedback goes back to step 2.

While waiting for the choice or the approval, continue with the work the look does not affect, per
[when to ask](business-questions.md#when-to-ask).

## How to build them

Build them with the [mockup capability](project-context.md#tools): self-contained static HTML with
sample data, no application code and no backend. Follow the existing design of the application where
the code shows it. A mockup shows confirmed behavior; it does not decide anything. Mark an undecided
point as a visible placeholder instead of guessing it; a question it raises goes to the user per the
[business questions procedure](business-questions.md). A subagent may write the pages; publishing them
and showing them to the user stays with the main agent.

## Where they live

- **With a plan:** the approved mockups in `{plans_dir}/{feature}/mockups/`, linked from the README
  together with a published link where there is one. Record the approval as a confirmed decision that
  names the files and add the mockup to the `references` of the tasks that build those screens.
- **Without a plan:** in `{work_dir}/mockups/{subject}/` per
  [project context](project-context.md#work-directory), named in the briefs of the implementers and in
  any handover. The work directory is temporary; until the work is done, nothing else keeps them.

Rejected variants are working material in `{work_dir}`; they do not go into the plan.

## An approved mockup binds the look

The implementation keeps the layout, the placement and order of the elements, the visual hierarchy and
the states the approved mockup shows. It need not match pixel for pixel; the application's components,
real data and technical limits may adjust details. A deviation that visibly changes the look or the use
of the screen needs the user's consent and an updated, re-approved mockup. For example, a different
spacing, a shorter label or a component the application already has instead of the drawn one is fine;
a menu approved on the left that ends up on the right, a missing section or a changed order of the main
blocks is a defect. A mockup not yet approved is only an illustration.

For behavior the PRD and the confirmed decisions hold. A conflict between them and an approved mockup is
a business question. Feedback on a mockup that changes behavior is a business decision: record it in
the decisions and, with a plan, reflect it in the PRD, the chapters and the tasks.
