# How deep is Alpaca News history? (G1 measurement, 2026-11-16)

SPIKE §3.1 left this open: public docs do not state the depth. Measured with this repo's key on 2026-11-16 (evening,
New York), about 130 free GET requests to `https://data.alpaca.markets/v1beta1/news`, no model calls. Counts, dates,
sources and status codes only; no headline text (SPIKE §3.2).

## Results

**Earliest article** (`sort=asc`, `start=2000-01-01T00:00:00Z`, `limit=1`):

| Ticker | Earliest `created_at` | Source | Articles in all history | Latest `created_at` |
|---|---|---|---|---|
| AAPL | 2026-04-29T10:31:17Z | fiscal.ai | 448 | 2026-11-16T21:31:25Z |
| NVDA | 2026-04-29T10:31:15Z | fiscal.ai | 656 | 2026-11-16T19:01:25Z |
| F | 2026-04-29T10:31:34Z | fiscal.ai | 173 | 2026-11-16T23:01:39Z |
| (no `symbols` filter) | 2026-04-29T02:31:18Z | fiscal.ai | not counted | |

The history starts on **2026-04-29**, about 6.5 months back, for every ticker and for the unfiltered feed. A
March window in each of 2015, 2017, 2019, 2021, 2023, 2024, 2025 and 2026 returned 0 articles for all three tickers.

**Articles per month** (all history, by `created_at`; April is from the 29th only):

| Ticker | 2026-04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 (to the 16th) |
|---|---|---|---|---|---|---|---|---|
| AAPL | 15 | 50 | 52 | 75 | 69 | 64 | 78 | 45 |
| NVDA | 11 | 77 | 122 | 99 | 85 | 101 | 120 | 41 |
| F | 9 | 34 | 26 | 33 | 17 | 22 | 22 | 10 |

**Articles per day on the 5 most recent sessions** (New York calendar day, midnight to midnight):

| Ticker | 2026-11-10 | 11-11 | 11-12 | 11-13 | 11-16 |
|---|---|---|---|---|---|
| AAPL | 7 | 1 | 2 | 3 | 4 |
| NVDA | 4 | 3 | 1 | 3 | 5 |
| F | 0 | 1 | 1 | 1 | 1 |

**Sources seen:** only `fiscal.ai`, on every counted article: 1,277 articles across the three tickers' full history, and
all 1,574 articles of the unfiltered feed on 2026-11-16 (each carried at least one symbol). `benzinga`, shown in
Alpaca's example responses, never appeared. In the six recorded fixture articles the `url` hosts are the original
publishers (newswires, news sites); `fiscal.ai` is the aggregator.

**Limits and status codes:**

| Request | Status | Note |
|---|---|---|
| `limit=51` | 400 | `invalid limit: larger than the allowed maximum of 50` |
| `limit=50` | 200 | 50 articles |
| `start=1990-01-01` | 200 | no error for a start before the history; first article is 2026-04-29 |
| `symbols` omitted | 200 | the whole feed |
| unknown symbol | 200 | 0 articles, no error |
| `include_content=true` | 200 | body text returned (531 characters on the sample); `alpaca.news` always sends `include_content=false` |

No request failed and no 403 was seen. `get_json` retries a 429 silently, but each measurement run took under 5 s,
so no backoff of note happened. The six probe responses above carried `x-ratelimit-limit: 10000` and
`x-ratelimit-remaining: 9999`. Whether that limit belongs to this key's plan or to every plan was not checked.

## What this means for the repo

- Headlines exist only for sessions from 2026-04-29 on. A backtest or dataset that spans earlier sessions has no
  news section; render "no headlines stored" rather than an empty list that looks like a quiet day `[INFERENCE]`.
- About 1–5 headlines per ticker per session for large caps and about 1 for F: a small prompt section. The
  analyze-call cost re-measure (REPO-PLAN D4) should still be done once headlines are rendered (week-5 packet).
- One aggregator (`fiscal.ai`) supplies everything, so `source` does not distinguish publishers; the url host does.
- A reader's own key may see a different depth or source mix; re-run the measurement below with that key.

## How to re-run

From the repo root, with keys in `~/.config/tradingresearch/verify.env`:

```python
from collections import Counter
from tradingresearch import alpaca
from tradingresearch.commands.common import alpaca_client
from tradingresearch.config import settings

with alpaca_client(settings()) as http:
    for t in ("AAPL", "NVDA", "F"):
        first = alpaca.news(http, [t], "2000-01-01T00:00:00Z", "2026-11-17T00:00:00Z", limit=1, max_articles=1)
        every = alpaca.news(http, [t], "2000-01-01T00:00:00Z", "2026-11-17T00:00:00Z")
        print(t, first[0]["created_at"], len(every), Counter(a["created_at"][:7] for a in every),
              Counter(a["source"] for a in every))
```

Per-day counts: the same call with `start`/`end` at New York midnights (`news.ny_midnight`). Status codes: a plain
`http.get(alpaca.NEWS_URL, params=...)` with the parameters in the table.
