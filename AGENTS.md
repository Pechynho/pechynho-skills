# pechynho skills — contributor instructions

- Edit only `base/` and `overlays/`. `plugins/` is generated: run `scripts/build.py` after every change
  and commit the result together with the source. `scripts/build.py --check` must pass.
- Everything in this repository is written in English.
- Keep the skills project-agnostic. Project-specific values go through
  `base/shared/project-context.md` (settings with defaults), never hard-coded paths or commands.
- Put tool-specific text in `<!-- platform:claude|codex -->` blocks or in `overlays/`; keep the shared
  wording tool-neutral ("question tool", "subagent").
- One rule lives in one place. Skills link to `shared/…` instead of repeating it.
- Bump `VERSION` for a release and validate with `claude plugin validate . --strict`.
