# Status

Last updated: 2026-08-17

## Current state
Build order steps 1-2 done, step 3 in progress.

- `eval/corpus/`: all 20 synthetic resume/ground-truth pairs generated
  (`resume_01.txt`/`.json` ... `resume_20.txt`/`.json`), via
  `eval/generate_corpus.py` against Gemini (`gemini-3.5-flash`, with
  `gemini-3.5-flash-lite` used for resumes 15-20 after the flash model's
  20-req/day free-tier cap was hit). Spot-checked across both models — no
  quality difference.
- `packages/parser/`: pure-library parser built. `models.py` (`Resume`,
  `Position`, `Education` Pydantic models — also imported by
  `generate_corpus.py` as the shared schema), `extract_text.py` (pypdf /
  python-docx), `parse.py` (`parse_resume(client, data, file_type) ->
  Resume` via Gemini structured output).
- One manual spot-check (`resume_01`) matched ground truth on every field
  except name casing (source ALL-CAPS vs. normalized ground truth).

## Next up
1. Build `eval/score.py` (build order step 3): run the parser against all
   20 corpus resumes, report field-level accuracy vs. ground truth. No
   formal baseline number exists yet.

## Known issues
None currently.

## Open questions
None.
