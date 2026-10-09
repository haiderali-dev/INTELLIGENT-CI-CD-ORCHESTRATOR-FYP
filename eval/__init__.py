"""Chatbot evaluation (BUILD_PROMPT 4.9).

Scores any parser on a JSONL dataset through the same pipeline the backend uses. See
``eval/runner.py`` for what a comparison holds fixed, and ``eval/dataset.py`` for the rule that
drafted items are never scored until a human has reviewed them.
"""
