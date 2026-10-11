"""Offline evaluation for the tutoring pipeline. A developer tool, not part of the service.

Principles (see docs/technical/design-ai-components.md §七 and zzz/ notes):
smoke test only, dataset built from observed failures and reviewed by a human,
deterministic grading through the production exit checks, one component at a time.
"""
