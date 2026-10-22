=== Under "## Chapter 6: algorithms", after the Section 6.4 item ===
- [ ] **Sections 6.5 and 6.6: the estimator's history and the plugin's cost, as built and as
      measured (D-073; Chapter 8, experiment E1).** Three sentences disagree with the
      implementation or with each other:
      - **Section 6.5 says history is "at most the last 50 builds per candidate job",** and the code
        agrees: `BuildHistoryService` reads up to `historyWindow` (50) builds from every job on the
        controller. So *h*, the builds one estimate examines, is up to 50 × the number of jobs: 1,500
        for the POC's 30 jobs.
      - **Section 6.6 says "h up to 50".** Replace it with "h up to 50 per job, so up to 1,500 for
        the POC's 30 jobs".
      - **Section 6.5 says estimates "are cached per job and refreshed only when a new build of a
        similar job completes".** The implementation caches a whole scoring pass instead
        (`BUILD_PROMPT.md` Part 4.3.7 step 2). The pass is keyed on the queued items and the rescore
        interval, and on a miss it estimates every queued job against the whole history.
      - **Section 6.6's "adds no measurable overhead ..., which we verify experimentally in the
        testing chapter".** Replace it with E1's measurement:
        - with 30 items queued, a queue-maintenance pass took 0.21 ms with the optimizer off and
          0.26 ms with it on (medians);
        - a full rescore took 2.2 ms at 30 items and 81 ms at 200 (with 340 history records);
        - it runs when the queue changes, and at most once a minute otherwise;
        - the algorithm alone took 86 µs at 200 items.
- [ ] **Section 6.2: aging does not prevent starvation under sustained load, with Appendix D's
      parameters (D-073; Chapter 8, experiment E3, a simulation).**
      - **What was measured:** over two hours of random arrivals at 95% utilisation on one
        executor, the LOW band's longest wait was 1,253 s with aging and the same without it, and
        every mean wait agreed within 2%.
      - **Why:**
        - the bonus is the same for every band and reaches its cap of 0.15 after 15 minutes, so
          under load the long-waiting jobs of every band sit at the cap together;
        - the cap equals the LOW–MEDIUM urgency gap (0.15) and is below the LOW–HIGH gap (0.35).
      - **What to write:** do not change the formula (Appendix C and the code agree on it). State
        this limitation in Section 6.2, and name band-aware aging, or a cap above 0.35, as future
        work.
      - **Note for the experiment:** in a 30-job burst of about five minutes, aging never acts at
        all (E2). An aging-ablation arm on `freestyle-30` should be expected to show no
        difference, and the report should say why.

=== Under "## Chapter 12 and Table 12.1", after the "honest shape" item ===
- [ ] **Say what Milestone 2's HIGH-band improvement cost in dependency order (D-073; Chapter 8,
      Section 8.8.4).** The figure is 271.5 s down to 39.1 s.
      - **The broken edges:** recomputed from its result files, the run that produced it started a
        job before a job it depends on had finished on 19 of the workload's 20 dependency edges.
        Runs 1 and 2 broke 10 and 18; FIFO broke 1.
      - **Why:** Milestone 2's dependency factor was a score, not a hold, and "met" meant the
        upstream's last build ever had succeeded.
      - **The comparison with version 2:** its gate breaks none. In simulation on the same
        workload, no policy that respects dependencies got the HIGH band below 155.9 s. Compare
        version 2 with "M2 dispatcher v1" only with that column beside it.
