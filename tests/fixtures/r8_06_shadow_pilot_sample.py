"""Nonmerge R8.06 advisory-only PR integration fixture.

This intentionally simple source exercises a real GitHub PR diff without
claiming that a synthetic change establishes review accuracy.
"""


def shadow_pilot_double(value: int) -> int:
    return value * 2
