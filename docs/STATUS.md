# Status

Last updated: 2026-08-12

## Current state
Repo skeleton in place: `pyproject.toml` (uv, ruff, pytest configured),
empty `packages/parser` package (import name `parser`), and
`eval/generate_corpus.py`, which calls the Gemini API to generate 20 varied,
messy synthetic resumes into `eval/corpus/` with matching ground-truth
`.json` files. Script has not yet been run — no `GEMINI_API_KEY` available
in this environment, so the corpus itself does not exist yet.

## Next up
1. Run `eval/generate_corpus.py` with a real key, spot-check a few
   resume/ground-truth pairs for quality.
2. Build order step 2 — the parser library in `packages/parser`.

## Parser accuracy
No baseline yet — parser doesn't exist.

## Known issues
`eval/corpus/` is unpopulated pending an actual Gemini API run.

## Open questions
None.
