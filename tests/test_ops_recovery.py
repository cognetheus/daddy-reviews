"""R8.05d.02: bounded read-only retry policy under transient and permanent faults."""
import pytest

from daddy_reviews.ops_recovery import (
    RecoveryError, RetryDecision, retry_classified_read_only,
)


def test_transient_retry_is_bounded_and_succeeds_only_after_verified_ok():
    observed = []
    def flaky(attempt):
        observed.append(attempt)
        return RetryDecision("retryable" if attempt < 3 else "ok")
    receipt = retry_classified_read_only(
        flaky, max_attempts=3, base_backoff_ms=0)
    assert receipt.status == "recovered"
    assert receipt.attempts == 3
    assert receipt.retry_count == 2
    assert receipt.read_only_operation is True
    assert observed == [1,2,3]


def test_permanent_failure_never_retries():
    calls=[]
    receipt=retry_classified_read_only(
        lambda n: calls.append(n) or RetryDecision("permanent"))
    assert calls == [1]
    assert receipt.status == "permanent_failure"
    assert receipt.retry_count == 0


def test_bounded_retries_exhaust_after_three_only():
    calls=[]
    receipt=retry_classified_read_only(
        lambda n: calls.append(n) or RetryDecision("retryable"),
        max_attempts=3, base_backoff_ms=0)
    assert receipt.status == "retry_exhausted"
    assert calls == [1,2,3]


def test_callback_errors_fail_closed_without_leaking_exception_message():
    def unsafe(n):
        raise RuntimeError("private-token=sensitive")
    result=retry_classified_read_only(unsafe)
    assert result.status == "permanent_failure"
    assert result.attempts == 1
    assert "private-token" not in repr(result)


def test_malformed_or_surprising_adapter_result_does_not_count_as_success():
    assert retry_classified_read_only(lambda n: None).status == "permanent_failure"
    assert retry_classified_read_only(
        lambda n: RetryDecision("another_status")).status == "permanent_failure"


@pytest.mark.parametrize("kwargs", [
    {"operation":"non_idempotent_publish"},
    {"max_attempts":0},
    {"max_attempts":4},
    {"max_attempts":True},
    {"base_backoff_ms":251},
    {"base_backoff_ms":-1},
    {"total_budget_ms":99},
    {"total_budget_ms":10001},
])
def test_unbounded_or_nonidempotent_retry_request_is_rejected(kwargs):
    with pytest.raises(RecoveryError):
        retry_classified_read_only(lambda n: RetryDecision("ok"), **kwargs)


def test_adapter_must_be_callable():
    with pytest.raises(RecoveryError):
        retry_classified_read_only(None)
