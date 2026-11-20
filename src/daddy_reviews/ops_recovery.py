"""R8.05d.02: bounded retries for explicitly classified idempotent operations.

Only an operator-controlled trusted adapter may supply the callback. A model,
repository file, PR text, or arbitrary shell command is NOT a valid callback.
Classification is closed-schema: transient errors may retry, permanent errors
and unexpected exceptions fail closed. No network, logs or secrets here.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Callable, Literal


class RecoveryError(ValueError):
    """Invalid retry policy or adapter contract."""


@dataclass(frozen=True)
class RetryDecision:
    status: Literal["ok", "retryable", "permanent"]


@dataclass(frozen=True)
class RetryReceipt:
    status: Literal["recovered", "permanent_failure", "retry_exhausted"]
    attempts: int
    retry_count: int
    elapsed_ms: int
    read_only_operation: bool


def retry_classified_read_only(
    adapter: Callable[[int], RetryDecision], *,
    operation: str = "fixed_health_probe",
    max_attempts: int = 3, base_backoff_ms: int = 10,
    total_budget_ms: int = 2000,
) -> RetryReceipt:
    """Retry only a declared read-only operation with a bounded deadline.

    Adapter must supply a trusted semantic classification; do not match
    attacker-controlled error messages to determine retriability.
    """
    if (operation not in ("fixed_health_probe", "authenticated_github_get")
            or not callable(adapter)
            or type(max_attempts) is not int or not 1 <= max_attempts <= 3
            or type(base_backoff_ms) is not int or not 0 <= base_backoff_ms <= 250
            or type(total_budget_ms) is not int or not 100 <= total_budget_ms <= 10000):
        raise RecoveryError("Invalid read-only retry budget or adapter")
    started = monotonic()
    attempts = 0
    final = "retry_exhausted"
    for attempt in range(1, max_attempts + 1):
        if (monotonic() - started) * 1000 >= total_budget_ms:
            break
        attempts = attempt
        try:
            decision = adapter(attempt)
            if not isinstance(decision, RetryDecision):
                final = "permanent_failure"
                break
        except Exception:
            final = "permanent_failure"
            break
        if decision.status == "ok":
            final = "recovered"
            break
        if decision.status != "retryable":
            final = "permanent_failure"
            break
        if attempt == max_attempts:
            break
        backoff = base_backoff_ms * (2 ** (attempt - 1))
        remaining = total_budget_ms - (monotonic() - started) * 1000
        if remaining <= backoff:
            break
        if backoff:
            sleep(backoff / 1000)
    return RetryReceipt(
        status=final, attempts=attempts, retry_count=max(0, attempts - 1),
        elapsed_ms=round((monotonic() - started) * 1000),
        read_only_operation=True,
    )
