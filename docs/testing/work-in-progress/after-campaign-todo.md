# Repository edits held until gate 5 and the final campaign (both at 8263a7e) are done

1. scripts/report/testing_annexure.py, section_campaign: a paragraph on the rehearsal at ac8305a
   (Parts A and B only; three backend steps failed in a DNS outage 06:41-06:56 and passed when
   re-run; its skipped test led to DF-42). Its attempt-1 logs: .tmp/campaign/ac8305a/.
   Consider copying a short excerpt of the outage errors into docs/testing/evidence/.
2. docs/decisions.md: D-073, with E1's figures from the FINAL campaign (check every E1 number:
   0.21/0.26 ms, 2.2 ms, 81 ms, 86 µs, 1.6 ms). E2/E3 are deterministic: confirm unchanged.
3. docs/report-updates.md: the three items in report-updates-new.md, E1 numbers re-checked.
4. docs/testing/chapter-8-software-testing.md: the draft, labels numbered, placeholders filled;
   run check_cited_tests.py against the register.
5. Generate: register (test_register.py --gate gate-5.log --ci ci-runs.json), figures
   (testing_figures.py --ci --complexity complexity CSV re-run at the final commit), annexure
   (testing_annexure.py --gate --system .tmp/system). Copy gate-5.log to docs/testing/evidence/.
6. PROGRESS.md: gate 5, the campaign, load and recovery tests, the chapter.
7. Chapter E1 section and 8.9.3: re-check every E1 number against the final campaign's CSV.
