"""One retry policy for every HTTP source: Alpaca bars and news, EDGAR, OpenRouter (REPO-PLAN week 4 and §8).

Exponential backoff with full jitter (AWS Builders' Library, "Timeouts, retries and backoff with jitter"): before retry
n (0-based) the client sleeps `uniform(0, min(cap, base * 2**n))`, so clients that failed together do not retry
together. A `Retry-After` header replaces the jitter, capped at `cap`.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TypeVar

import httpx

T = TypeVar("T")
TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)  # connection and timeout errors


class HttpError(RuntimeError):
    """A non-success reply as `<source> <status>: <text>`; retryable on 429 and 5xx only."""

    def __init__(self, source: str, status: int, text: str, retry_after: float | None = None) -> None:
        super().__init__(f"{source} {status}: {text}")
        self.status = status
        self.retry_after = retry_after
        self.retryable = status == 429 or status >= 500

    @classmethod
    def of(cls, source: str, response: httpx.Response, limit: int = 200) -> HttpError:
        return cls(source, response.status_code, response.text[:limit],
                   retry_after(response.headers.get("Retry-After")))


def retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds from a Retry-After header (delay-seconds or an HTTP date); None when absent or unreadable."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def retryable(exc: BaseException) -> bool:
    """429, 5xx, connection and timeout errors. Never another 4xx, never a reply that arrived and was parsed."""
    return isinstance(exc, TRANSIENT) or getattr(exc, "retryable", False) is True


@dataclass(frozen=True)
class Policy:
    """At most `tries` calls within `budget` seconds. `sleep`, `rng` and `clock` are injected so tests run instantly."""

    tries: int = 4
    base: float = 1.0
    cap: float = 30.0
    budget: float = 300.0
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)
    rng: random.Random = field(default_factory=random.Random, repr=False, compare=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)

    def wait(self, exc: BaseException, retry: int) -> float:
        """Seconds before retry `retry` (0-based): the server's Retry-After if it sent one, else full jitter."""
        after = getattr(exc, "retry_after", None)
        if after is not None:
            return min(self.cap, after)
        return self.rng.uniform(0.0, min(self.cap, self.base * 2**retry))

    def call(self, fn: Callable[[], T]) -> T:
        """`fn()` until it succeeds, fails for good, or the tries or the time budget run out; the last error is raised."""
        start = self.clock()
        for attempt in range(1, self.tries + 1):
            try:
                return fn()
            except Exception as exc:
                if not retryable(exc):
                    counted(exc, attempt, "after")
                    raise
                if attempt == self.tries:
                    counted(exc, attempt, "gave up after")
                    raise
                wait = self.wait(exc, attempt - 1)
                if self.clock() - start + wait > self.budget:
                    counted(exc, attempt, "gave up after", f"; a {wait:.1f}s wait would pass the {self.budget:g}s budget")
                    raise
                self.sleep(wait)
        raise AssertionError("unreachable: the loop returns or raises")


def counted(exc: Exception, attempts: int, verb: str, why: str = "") -> None:
    """End the error's message with the tries; its type is kept, so core still reads a ProviderError's `code`."""
    exc.attempts = attempts  # type: ignore[attr-defined]
    if attempts > 1 or why:
        exc.args = (f"{exc} ({verb} {attempts} {'try' if attempts == 1 else 'tries'}{why})",)


DEFAULT = Policy()
