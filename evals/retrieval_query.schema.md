# `evals/retrieval_query.jsonl`: labelled retrieval queries

One JSON object per line. The learner writes the 30 real queries (REPO-PLAN §1.3); this file ships empty.
`tr retrieval eval --queries evals/retrieval_query.jsonl` validates every line against the index, then prints recall.

## Fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique within the file, e.g. `q07`. |
| `ticker` | yes | Only this ticker's documents are searched. |
| `as_of` | yes | An NYSE session (`YYYY-MM-DD`). Only documents available at or before that session's close are searched. |
| `kind` | yes | `lookup` (a fact stated in prose), `numeric` (a value in a table or sentence) or `event` (an 8-K item or a headline). |
| `text` | yes | The question, as a user would ask it. |
| `gold` | yes | 1-3 objects `{"doc": <doc id>, "quote": <text>}`. |
| `answer` | no | The expected answer, for the reader. Not scored. |
| `notes` | no | Free text. Not scored. |

- **Doc id.** A filing document is `<accession>/<file name>`, e.g. `0009999999-26-000101/fakea-ex991.htm`. A headline is
  `headline/<article id>`. `tr retrieval query` prints chunk ids, which are `<doc id>#<n>`.
- **Gold is a quote, not a chunk id.** At eval time each quote is matched against every chunk of its document (spaces
  and line breaks are ignored), so a label survives a change of chunk size or chunker. A table row is quoted as the
  chunker prints it: cells joined by ` | `, e.g. `Net income | $701 | $633`.

## Validation (any failure stops the eval)

- the fields above, no others; `id` unique; `kind` one of the three; `as_of` an NYSE session; 1-3 golds;
- each gold `doc` is in the index and belongs to `ticker`;
- each gold `doc` was available at or before the `as_of` cutoff (a label must not point at the future);
- each `quote` is found in at least one chunk of its `doc`.

## Scores

Per retriever (G13a: `bm25`), for all queries and per `kind`, at k = 1, 5, 10, 20, with the counts next to the rates:

- `recall_any@k`: share of queries with at least one chunk of at least one gold quote in the top k.
- `recall_frac@k`: per query, the share of its gold quotes with a chunk in the top k; then averaged over queries.

The look-ahead mask is applied before ranking: future documents never take a place in the top k.

## Examples (invented FAKEA data; they validate against the test index in `tests/fixtures/retrieval/`)

```jsonl
{"id": "fakea-01", "ticker": "FAKEA", "as_of": "2026-11-05", "kind": "numeric", "text": "What was FakeA's net income for the quarter ended September 30, 2026?", "gold": [{"doc": "0009999999-26-000101/fakea-ex991.htm", "quote": "Net income | $701 | $633"}], "answer": "$701 million", "notes": "income statement row of the EX-99.1"}
{"id": "fakea-02", "ticker": "FAKEA", "as_of": "2026-11-05", "kind": "lookup", "text": "Why did FakeA record restructuring charges in the third quarter of 2026?", "gold": [{"doc": "0009999999-26-000101/fakea-ex991.htm", "quote": "closure of the Shelbyville plant"}, {"doc": "0009999999-26-000101/fakea-8k_20261029.htm", "quote": "Restructuring charges | (45)"}], "answer": "closing the Shelbyville plant", "notes": "prose in the press release; the 8-K table carries the amount"}
```
