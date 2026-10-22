# pechynho skills — contributor instructions

- Edit only `base/` and `overlays/`. `plugins/` is generated: run `scripts/build.py` after every change
  and commit the result together with the source. `scripts/build.py --check` must pass.
- Every change to a tool in `base/shared/` or `scripts/` comes with tests in `tests/`;
  `python3 -m unittest` and `node --test tests/*.test.mjs` must pass. Tests use only the standard
  library and Node's built-ins, like the tools themselves.
- Everything in this repository is written in English.
- Keep the skills project-agnostic. Project-specific values go through
  `base/shared/project-context.md` (settings with defaults), never hard-coded paths or commands.
- Put tool-specific text in `<!-- platform:claude|codex -->` blocks or in `overlays/`; keep the shared
  wording tool-neutral ("question tool", "subagent").
- Skills link to their sibling skills (`../../programming/SKILL.md`), so they are meant to be
  installed together as the plugin, not one by one.
- One rule lives in one place. Skills link to `shared/…` instead of repeating it.
- Bump `VERSION` for a release and validate with `claude plugin validate . --strict`.
