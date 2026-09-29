"""Retry with exponential backoff and full jitter, honouring a server's Retry-After."""

import random
import time
from collections.abc import Callable


def call_with_retries[T](
    call: Callable[[], T],
    *,
    is_retryable: Callable[[Exception], bool],
    retry_after: Callable[[Exception], float | None] = lambda exc: None,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> T:
    """Run `call`; on a retryable error wait and try again, up to `attempts` calls in total.

    The wait is the server's Retry-After when given, otherwise a random fraction of
    `base_delay * 2**n` ("full jitter"), never more than `max_delay`. Non-retryable errors,
    and the last retryable one, propagate unchanged.
    """
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            if not is_retryable(exc) or attempt == attempts - 1:
                raise
            suggested = retry_after(exc)
            backoff = jitter() * base_delay * 2**attempt
            sleep(min(max_delay, suggested if suggested is not None else backoff))
    raise AssertionError("unreachable")  # pragma: no cover - the loop always returns or raises
