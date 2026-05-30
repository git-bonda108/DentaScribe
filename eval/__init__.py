"""DentaScribe evaluation harness.

Goal: measure end-to-end quality against ground-truth annotations so every
change to a prompt, agent, or model can be scored against a regression baseline.
Lives outside the agent pipeline — it never mutates `SwarmState` or any agent.
"""
