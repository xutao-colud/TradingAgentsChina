from __future__ import annotations

import unittest

from app.network.retry import RetryExhaustedError, RetryPolicy, retry_call


class RetryCallTest(unittest.TestCase):
    def test_retries_transient_failure_with_bounded_backoff(self) -> None:
        attempts = 0
        delays: list[float] = []

        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("connection reset")
            return "verified payload"

        result = retry_call(
            flaky,
            operation_name="test provider",
            policy=RetryPolicy(3, 0.1, 0.5),
            sleep=delays.append,
        )

        self.assertEqual(result, "verified payload")
        self.assertEqual(attempts, 3)
        self.assertEqual(delays, [0.1, 0.2])

    def test_does_not_retry_nonrecoverable_permission_error(self) -> None:
        attempts = 0

        def denied() -> str:
            nonlocal attempts
            attempts += 1
            raise PermissionError("permission denied")

        with self.assertRaises(PermissionError):
            retry_call(
                denied,
                operation_name="test provider",
                policy=RetryPolicy(3, 0.1, 0.5),
                sleep=lambda _: self.fail("nonrecoverable failures must not sleep"),
            )
        self.assertEqual(attempts, 1)

    def test_marks_exhausted_transient_failure_with_attempt_count(self) -> None:
        attempts = 0

        def unavailable() -> str:
            nonlocal attempts
            attempts += 1
            raise OSError("temporary provider outage")

        with self.assertRaises(RetryExhaustedError) as raised:
            retry_call(
                unavailable,
                operation_name="test provider",
                policy=RetryPolicy(2, 0.1, 0.5),
                sleep=lambda _: None,
            )
        self.assertEqual(attempts, 2)
        self.assertEqual(raised.exception.attempts, 2)
        self.assertIn("test provider", str(raised.exception))
