# The testing chapter: what is left (2026-10-22, 12:20)

Done:
- the evidence campaign at `31eb935`; D-073, D-075, DF-43 and DF-44 (`0285f30`);
- the register, figures and annexure builders in `scripts/report/`, and their outputs;
- `scripts/report/check_citations.py`: every test the chapter cites ran and passed (76 of 76);
- the draft, reviewed line by line against the data and the records.

Left, in order:
1. Gate run 7 at the commit after `0285f30`, on mains power. Gate run 6 failed one check when the
   laptop went onto battery and was suspended for 22 minutes (CLAUDE.md, environment facts).
2. On mains power, after the gate: `python scripts/system_load_test.py`, then
   `python scripts/recovery_test.py`. Both write to `.tmp/system`.
3. Refetch the CI history, then rebuild the register, figures and annexure, with
   `--gate docs/testing/evidence/gate-run-7-<sha>.log --system .tmp/system`.
4. In the draft, gate run 7 replaces gate run 5: Section 8.1's results in brief, the
   static-analysis table and the note under it, the metrics row in 8.6.2, 8.7.1's Operations,
   8.7.2's replayed end-to-end sentence, and the gate runs in 8.9.4's limits. `values.json` too:
   `GATE_COMMIT` and `R_METRICS_CHECK`.
5. `fill_placeholders.py chapter-8-draft.md <out> .tmp/campaign/31eb935 .tmp/system values.json`,
   then `assemble_chapter.py` into `docs/testing/chapter-8-software-testing.md`, then
   `python scripts/report/check_citations.py`.
6. Remove this folder, check the chapter off in `PROGRESS.md`, commit, push, and see CI pass.
