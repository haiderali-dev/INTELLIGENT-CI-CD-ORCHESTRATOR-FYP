"""Explaining why a run failed (T5.9).

``redact`` removes what a log must not carry onward, ``analysis`` works out what the log shows,
``explainer`` asks the model to put that into words and checks every word it quotes, and
``factory`` wires the explainer for the configured ``LLM_MODE``. The run, its chain and its log
are fetched by ``app.services.failures``.
"""
