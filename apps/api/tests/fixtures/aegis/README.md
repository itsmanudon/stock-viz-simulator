# Recorded Aegis responses

Contract fixtures for the Aegis read sync (`stockviz.services.aegis`). Aegis owns
the read contract, so StockViz builds against recorded responses, never a live
call in tests.

## Where they come from

They start from a live recording made on 10 Nov 2026 against a local Aegis stack
(`docs/contracts/recorded/feed-documents-mapped.json` in the workspace
repository: synthetic articles through the real pipeline, `offline` profile).
That recording predates the 11 Nov feed changes, so it was brought up to the
current shape:

- `entities` on every bundle (AG-2) and `withdrawal: null`;
- headlines and entities renamed to two StockViz symbols, Apple (`AAPL`) and
  Reliance (`RELIANCE.NS`);
- one `mixed` sentiment label (AG-4) and one empty `published_at` (AG-12);
- page 2: a tombstone for the first document (AG-11) and the second document
  re-analysed, with a new sentiment analysis and a second manifest;
- version 2 cursors (AG-8), two feed pages and two mapping pages, with
  `provider_id` mappings `stockviz:<ticker>` as in Aegis's
  `data/instruments/stockviz.json`.

| File | Route |
| --- | --- |
| `feed-page-1.json`, `feed-page-2.json`, `feed-empty.json` | `GET /api/v1/feed/documents` |
| `mappings-page-1.json`, `mappings-page-2.json` | `GET /api/v1/assets/mappings` |

## Checked against Aegis

Every file validates with Aegis's own strict response models (unknown and
missing fields rejected) at `aegis-news` `dev` `f3539f4`:
`aegis.contracts.feed.FeedResponse` for the feed, and
`aegis.contracts.api.CollectionResponse[aegis.domain.models.AssetMapping]` for
the mappings. Rerun that check after any change to Aegis's feed contract, from
the `aegis-news` checkout:

```bash
uv run python -c "
import json, sys
from aegis.contracts.api import CollectionResponse
from aegis.contracts.feed import FeedResponse
from aegis.domain.models import AssetMapping
d = sys.argv[1]
for n in ('feed-page-1', 'feed-page-2', 'feed-empty'):
    FeedResponse.model_validate(json.load(open(f'{d}/{n}.json')))
for n in ('mappings-page-1', 'mappings-page-2'):
    CollectionResponse[AssetMapping].model_validate(json.load(open(f'{d}/{n}.json')))
print('ok')
" <path to this folder>
```
