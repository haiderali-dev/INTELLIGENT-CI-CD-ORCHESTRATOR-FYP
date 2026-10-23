"""Experiment v2: the harness that compares the optimizer with its observe-only control (Part 4.8).

``python -m experiment`` has five commands: ``setup`` creates a workload's jobs on a controller,
``warmup`` runs them to build history, ``run`` measures one repetition, ``analyze`` computes its
KPIs and ``report`` writes Chapter 12's table, CSV and charts. The harness talks to Jenkins only
through its REST API and the plugin's ``/dynamic-queue`` endpoints: no Groovy and no script
console (rule 1.5), which is how Milestone 2's harness worked and why it was replaced.

The package uses the standard library only, so the tests run in CI's backend environment and the
harness runs under any Python from 3.12.
"""
