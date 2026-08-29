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

News ingest no longer scores inline. `news.article.ingested` drives the
sentiment worker; `news.sentiment.scored` drives the ticker-scoped aggregate
worker. `sentiment_aggregate_refresh` still runs weekdays at 16:55 ET as a
full-universe reconciliation pass after `symbol_metrics_refresh`.

If `SENTIMENT_PROVIDER=none`, the sentiment worker records the inbox receipt
and does not emit `news.sentiment.scored`. `score-sentiment` / `backfill_unscored`
remain the way to score the archive after a provider is configured.

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

## A concrete `http` provider: the sentiment-pipeline service

[`sentiment-pipeline`](https://github.com/itsmanudon/sentiment-pipeline)
implements this contract at `POST /v1/score` (`services/intelligence/app/api/score.py`).

Its LLM extraction step already emits, per event, a `sentiment` in `[-1, 1]`
and a `confidence` in `[0, 1]` — the same ranges and the same polarity
`SentimentScore` defines, so the endpoint is a **mapping layer only**. It calls
the same `extract_events()` the pipeline's own Celery task calls; no prompt,
model call, or scoring rule is re-implemented, and it deliberately does not
persist articles, dedupe, or run opportunity scoring.

Mapping decisions worth knowing:

| Situation | Result |
| --- | --- |
| Article yields several events | The one matching the requested `ticker` wins; within the matches, highest `confidence`. Averaging would blur the signal `confidence` exists to express. |
| Article yields no market-relevant event | `null` — "nothing to say" is not "said neutral", and a null is retried by `backfill_unscored`. |
| `ANTHROPIC_API_KEY` unset on the service | **503**, not a batch of nulls. A batch of nulls is indistinguishable from "nothing was scoreable" and would silently degrade this pipeline. |

`model` comes back as `<llm_model>/extraction-v<SCHEMA_VERSION>` (e.g.
`claude-sonnet-5/extraction-v1`) — the extraction schema version is part of the
scorer's identity, so a bumped contract re-scores rather than silently mixing.

Auth: the service accepts `Authorization: Bearer <key>` as an equivalent of its
native `X-API-Key`, which is what `SENTIMENT_SERVICE_TOKEN` sends.

### Running it locally against the docker stack

```bash
# infra/.env — compose does NOT read apps/api/.env
SENTIMENT_PROVIDER=http
SENTIMENT_SERVICE_URL=http://host.docker.internal:18000/v1
SENTIMENT_MODEL_HINT=sentiment-pipeline
```

`SENTIMENT_SERVICE_URL` carries the `/v1` prefix because `HttpProvider` posts to
`{base_url}/score`. Then:

```bash
docker exec stockviz-api python -m stockviz.cli news AAPL MSFT NVDA
docker exec stockviz-api python -m stockviz.cli score-sentiment
docker exec stockviz-api python -m stockviz.cli sentiment-aggregate
curl http://127.0.0.1:8000/v1/symbols/NVDA/sentiment
```

**Caveat — market specialisation.** The extractor's system prompt is written for
*Indian* financial news (NSE symbols, crore/lakh conversion). The schema and the
sentiment/confidence semantics are market-agnostic and map cleanly, but scoring a
US-equity corpus with it is running the model outside its prompt's stated domain.
Treat US scores as unvalidated until the prompt is generalised or a second
profile is added.
