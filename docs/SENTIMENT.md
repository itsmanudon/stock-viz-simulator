# Sentiment scoring

How StockViz gets a sentiment reading for a news article, and how to plug a
separate sentiment-analysis service into it.

## Providers

Scoring goes through one interface, `SentimentProvider`
(`apps/api/src/stockviz/services/sentiment/base.py`). Which implementation runs
is decided by `SENTIMENT_PROVIDER`:

| Value | Implementation | Needs |
| --- | --- | --- |
| `none` | `NullProvider` — scores nothing | nothing |
| `anthropic` | Claude Haiku, batched | `ANTHROPIC_API_KEY` |
| `http` | A standalone scoring service | `SENTIMENT_SERVICE_URL` |

Left blank, it resolves to `anthropic` when `ANTHROPIC_API_KEY` is set and
`none` otherwise, so a deployment that predates this setting is unaffected.

A provider never raises for one document. Anything it can't score comes back as
`None`, which is stored as NULL and picked up later by the backfill — that's the
difference between "we don't know" and "we judged this neutral".

## Wire contract for the `http` provider

This is the seam a separate repository implements. Version it: additive changes
are fine, but a breaking change needs a new path (`/v2/score`).

### Request

```http
POST {SENTIMENT_SERVICE_URL}/score
Content-Type: application/json
Authorization: Bearer {SENTIMENT_SERVICE_TOKEN}    # omitted when unset
```

```json
{
  "documents": [
    { "text": "Acme beats estimates\n\nRevenue up 12% YoY.", "ticker": "ACME" },
    { "text": "Regulator opens inquiry into Acme", "ticker": "ACME" }
  ]
}
```

- `text` is the headline, or headline + `\n\n` + summary when a summary exists.
- `ticker` may be `null` for general-market news.
- Batches are at most 50 documents (`HttpProvider.DEFAULT_BATCH_SIZE`).

### Response

```json
{
  "model": "finbert-v2",
  "results": [
    { "label": "positive", "score": 0.82, "confidence": 0.91 },
    { "label": "negative", "score": -0.55 }
  ]
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `model` | string | Recorded against every score. Change it when the model changes — that's what makes re-scoring and A/B comparison possible. |
| `results` | array | **Must** be the same length as `documents`, in the same order. |
| `results[].score` | number | Required. `[-1, 1]`; values outside are clamped. |
| `results[].label` | string | Optional. `positive` \| `neutral` \| `negative`. Derived from `score` when absent or unrecognised. |
| `results[].confidence` | number | Optional. `[0, 1]`. Omit rather than guessing — NULL means "unknown", not "zero". |
| `results[].model` | string | Optional per-result override of the top-level `model`. |

Return `null` in place of a result object for a document you couldn't score. It
is stored as NULL and retried by the backfill.

### Failure handling

- Non-2xx and transport errors are retried three times with exponential backoff.
- After that the whole batch degrades to `None` — nothing is written, so the
  backfill will retry those articles later.
- A `results` array whose length doesn't match `documents` is rejected outright:
  a partial response would silently misalign scores against articles.

## Storage

`news_sentiment` holds one row per `(article_id, model)`:

```
id, article_id -> news_articles.id
model          # "claude-haiku-4-5-20251001" | "finbert-v2" | ...
label          # positive | neutral | negative
score          # Numeric(6,4), -1.0000 .. 1.0000
confidence     # Numeric(5,4), nullable
scored_at
UNIQUE (article_id, model)
```

The unique constraint means re-running a model updates in place, while adding a
second model writes alongside rather than overwriting — so two models can be
compared on the same corpus.

`news_articles.sentiment` remains as a denormalized "current best" label so the
existing badge keeps working with no read changes.

## Aggregation

`refresh_symbol_sentiment` rolls per-article scores into a trailing 7-day mean
per ticker, written to `symbol_metrics.sentiment_7d` alongside
`sentiment_article_count`. A symbol with no scored articles in the window gets
NULL, not `0.0`.

That aggregate is what the rest of the app reads:

- **Screener** — `sentiment_min` / `sentiment_max` filters.
- **Recommendation engine** — a seventh vote
  (`_vote_positive_sentiment`), firing above `+0.20`. Max score is now 7; the
  recommend threshold is unchanged at 4.
- **`GET /v1/symbols/{ticker}/sentiment`** — daily series plus the rolling
  figure, for the ticker page's chart overlay.

## Operating it

```bash
# Score articles that have no result yet for the active model.
uv --directory apps/api run python -m stockviz.cli score-sentiment
uv --directory apps/api run python -m stockviz.cli score-sentiment --since 2026-01-01 --limit 500

# Recompute the per-symbol rolling average.
uv --directory apps/api run python -m stockviz.cli sentiment-aggregate
```

Both have scheduler twins: news ingest scores new articles inline (every 4h),
and `sentiment_aggregate_refresh` runs weekdays at 16:55 ET, right after the
metrics refresh so both land on the same `symbol_metrics` rows in order.

`SENTIMENT_DAILY_DOCUMENT_CAP` (default 2000) bounds how many documents any one
run will score, so a runaway backfill can't quietly burn an API budget.

## Connecting a new service — checklist

1. Implement `POST /score` per the contract above.
2. Deploy it somewhere the API can reach.
3. Set `SENTIMENT_PROVIDER=http`, `SENTIMENT_SERVICE_URL`, and (if the service
   authenticates) `SENTIMENT_SERVICE_TOKEN`.
4. Backfill the archive: `python -m stockviz.cli score-sentiment`.
5. Recompute aggregates: `python -m stockviz.cli sentiment-aggregate`.

Existing scores from other models are untouched, so you can run both and compare
before switching over.

## Why a service rather than a library

Keeping the model in its own process keeps torch/transformers and any CUDA
runtime out of the API image — which matters on Render's free tier — and lets
the two repositories deploy independently. If the model is small enough for CPU
inference and you'd rather import it, add a `LocalModelProvider` next to the
existing ones; nothing outside `services/sentiment/` needs to change.
