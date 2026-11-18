"""The shared retry policy (REPO-PLAN week 4, §8): the full-jitter schedule worked out by hand, Retry-After, what is
never retried, the time budget, the attempt count in the error, and the Alpaca and EDGAR wiring at the HTTP transport."""

import random
from datetime import UTC, datetime

import httpx
import pytest

from tradingresearch import alpaca, retry
from tradingresearch.edgar import Edgar
from tradingresearch.providers.openrouter import OpenRouterError
from tradingresearch.retry import HttpError, Policy


class Timeline:
    """The injected clock and sleep: sleeping moves the clock, so the budget is checked without waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


class Upper(random.Random):
    """A seeded RNG whose `uniform` returns the top of the range and records each range, so the schedule is exact."""

    def __init__(self) -> None:
        super().__init__(0)
        self.ranges: list[tuple[float, float]] = []

    def uniform(self, a: float, b: float) -> float:
        self.ranges.append((a, b))
        return b


def policy(timeline: Timeline, rng: random.Random, **kw) -> Policy:
    return Policy(**{"tries": 4, "base": 1.0, "cap": 3.0, "budget": 100.0, **kw},
                  sleep=timeline.sleep, rng=rng, clock=timeline.clock)


def failing(*errors: Exception, then: object = "ok"):
    """A call that raises `errors` in order, then returns `then`; `calls` counts the tries."""
    queue = list(errors)

    def call():
        call.calls += 1
        if queue:
            raise queue.pop(0)
        return then

    call.calls = 0
    return call


def test_full_jitter_bounds_double_per_retry_and_stop_at_the_cap():
    # retry n sleeps uniform(0, min(cap, base * 2**n)): base 1, cap 3 -> (0, 1), (0, 2), (0, min(3, 4)) = (0, 3)
    timeline, rng = Timeline(), Upper()
    call = failing(*(HttpError("X", 503, "down") for _ in range(3)))
    assert policy(timeline, rng).call(call) == "ok"
    assert rng.ranges == [(0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
    assert timeline.slept == [1.0, 2.0, 3.0] and call.calls == 4


def test_a_seeded_rng_stays_inside_each_bound():
    timeline = Timeline()
    call = failing(*(HttpError("X", 500, "down") for _ in range(3)))
    policy(timeline, random.Random(7)).call(call)
    bounds = [1.0, 2.0, 3.0]
    assert len(timeline.slept) == 3 and all(0.0 <= s <= b for s, b in zip(timeline.slept, bounds, strict=True))


def test_the_last_error_is_raised_with_the_attempt_count():
    timeline = Timeline()
    call = failing(*(HttpError("Alpaca", 503 + n, "down") for n in range(4)))
    with pytest.raises(HttpError) as raised:
        policy(timeline, Upper()).call(call)
    assert str(raised.value) == "Alpaca 506: down (gave up after 4 tries)"
    assert raised.value.attempts == 4 and call.calls == 4 and len(timeline.slept) == 3


def test_retry_after_replaces_the_jitter_and_is_capped():
    timeline, rng = Timeline(), Upper()
    call = failing(HttpError("X", 429, "slow", retry_after=2.5), HttpError("X", 429, "slow", retry_after=60.0))
    policy(timeline, rng).call(call)
    assert timeline.slept == [2.5, 3.0] and rng.ranges == []  # the server's wait, capped at 3; no jitter drawn


def test_retry_after_reads_seconds_and_http_dates():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    assert retry.retry_after("7", now) == 7.0
    assert retry.retry_after("Mon, 16 Nov 2026 12:00:30 GMT", now) == 30.0
    assert retry.retry_after(None) is None and retry.retry_after("soon") is None


def test_a_400_is_raised_at_once_with_its_message_unchanged():
    timeline = Timeline()
    call = failing(HttpError("Alpaca", 400, "bad symbol"))
    with pytest.raises(HttpError) as raised:
        policy(timeline, Upper()).call(call)
    assert str(raised.value) == "Alpaca 400: bad symbol" and raised.value.attempts == 1
    assert call.calls == 1 and timeline.slept == []


def test_only_429_5xx_and_connection_errors_are_retryable():
    assert [HttpError("X", s, "").retryable for s in (400, 401, 403, 404, 422, 429, 500, 503)] == [
        False, False, False, False, False, True, True, True]
    assert retry.retryable(httpx.ConnectError("refused")) and retry.retryable(httpx.ReadTimeout("slow"))
    assert retry.retryable(OpenRouterError(502, "upstream")) and not retry.retryable(OpenRouterError(402, "credits"))
    assert not retry.retryable(ValueError("a parsed reply that was wrong"))


def test_a_non_retryable_error_after_retries_names_the_tries():
    timeline = Timeline()
    call = failing(httpx.ConnectError("refused"), OpenRouterError(400, "bad model"))
    with pytest.raises(OpenRouterError) as raised:
        policy(timeline, Upper()).call(call)
    assert str(raised.value) == "OpenRouter 400: bad model (after 2 tries)" and raised.value.code == "http_400"


def test_the_time_budget_stops_retries_before_the_wait_that_would_pass_it():
    # budget 4 s, waits 1, 2, 3: elapsed 0+1 ok, 1+2 = 3 ok, 3+3 = 6 > 4 -> give up after the third try
    timeline = Timeline()
    call = failing(*(HttpError("X", 503, "down") for _ in range(3)))
    with pytest.raises(HttpError) as raised:
        policy(timeline, Upper(), budget=4.0).call(call)
    assert str(raised.value) == "X 503: down (gave up after 3 tries; a 3.0s wait would pass the 4s budget)"
    assert call.calls == 3 and timeline.slept == [1.0, 2.0]


def test_the_budget_counts_time_spent_inside_the_calls():
    timeline = Timeline()

    def slow():
        timeline.now += 10.0  # a 10 s timeout
        raise httpx.ReadTimeout("slow")

    with pytest.raises(httpx.ReadTimeout, match=r"gave up after 1 try; a 1.0s wait would pass the 5s budget"):
        policy(timeline, Upper(), budget=5.0).call(slow)


# ---------- wiring: the clients use the policy ----------

def serving(*responses: httpx.Response, seen: list[httpx.Request]) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_alpaca_get_json_retries_a_503_honouring_retry_after():
    timeline, seen = Timeline(), []
    http = serving(httpx.Response(503, headers={"Retry-After": "2"}, text="busy"),
                   httpx.Response(200, json={"bars": {}}), seen=seen)
    got = alpaca.get_json(http, alpaca.DATA_URL, {"symbols": "AAPL"}, policy=policy(timeline, Upper()))
    assert got == {"bars": {}} and len(seen) == 2 and timeline.slept == [2.0]


def test_alpaca_get_json_raises_a_403_with_alpacas_message_and_no_retry():
    timeline, seen = Timeline(), []
    http = serving(httpx.Response(403, text="forbidden"), seen=seen)
    with pytest.raises(RuntimeError, match=r"^Alpaca 403: forbidden$"):
        alpaca.get_json(http, alpaca.DATA_URL, {}, policy=policy(timeline, Upper()))
    assert len(seen) == 1 and timeline.slept == []


def test_edgar_retries_a_500_then_caches_and_a_404_is_not_retried(tmp_path):
    timeline, seen = Timeline(), []
    client = Edgar("tradingresearch test@example.com", tmp_path, policy=policy(timeline, Upper()))
    client._http = serving(httpx.Response(500, text="oops"), httpx.Response(200, json={"0": {"ticker": "AAPL",
                                                                                             "cik_str": 320193}}),
                           httpx.Response(404, text="no such filer"), seen=seen)
    assert client.cik("AAPL") == 320193 and (tmp_path / "company_tickers.json").exists()
    assert len(seen) == 2 and timeline.slept == [1.0]
    with pytest.raises(HttpError, match=r"^EDGAR 404: no such filer$"):
        client.company_facts("AAPL")
    assert len(seen) == 3
