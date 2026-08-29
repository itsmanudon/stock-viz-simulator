# Massive US Market Data Shadow Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a private, non-persistent Massive US daily-bar shadow adapter and quantified comparison workflow while preserving yfinance as StockViz's sole persisted/default market-data provider.

**Architecture:** Keep `fetch_daily_bars()` and `PriceBar` as the existing production seam, add generic canonical bar semantics plus a provider-isolated Massive adapter, and compare Massive with yfinance in memory. Persist only yfinance bars, write live comparison artifacts only under a gitignored private directory, and validate deterministic and live-provider container workflows separately.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLModel/SQLAlchemy, Alembic, httpx, pandas/yfinance, pytest, PostgreSQL 16, Kafka 3.9, Docker Compose, PowerShell.

**Spec:** `docs/superpowers/specs/2026-08-29-massive-us-market-data-shadow-design.md`

## Global Constraints

- Preserve `PriceBar.source` as the only provider-provenance field; do not add a second provider field.
- Add only generic `adjustment_semantics` and `session_scope` bar semantics.
- yfinance remains the sole persisted/default provider; Alpha Vantage remains its existing fallback.
- Massive bars and Massive corporate-action payloads are never persisted or served by FastAPI/Next.js.
- Do not add Massive to the `price_bars` primary key and do not create a shadow-history table.
- Exclude same-New-York-date daily bars from completed-bar persistence.
- Parse Massive JSON numbers directly to `Decimal`; never round fractional volume silently.
- Determine the fixed database volume scale from a live precision audit. If credentials are unavailable, stop before the volume migration rather than guessing.
- Individual-subscription execution stays private/local. Technical approval and production/commercial licensing approval are independent gates.
- Do not implement TrueData, NSE, BSE, or a production provider cutover.
- Preserve every existing test; document unrelated baseline failures separately.

## File Map

- `apps/api/src/stockviz/services/ingest/bar_semantics.py` — generic adjustment/session enums, New York session labeling, and completed-bar filter.
- `apps/api/src/stockviz/services/ingest/prices.py` — existing `BarRecord`, yfinance/Alpha Vantage mapping, persistence, and default orchestration.
- `apps/api/src/stockviz/services/ingest/providers/massive.py` — Massive-only HTTP/payload/timestamp/action/open-close adapter.
- `apps/api/src/stockviz/services/ingest/shadow.py` — provider-neutral mismatch statistics, precision audit, action windows, and classifications.
- `apps/api/src/stockviz/services/ingest/shadow_report.py` — private JSON and Markdown report serialization.
- `apps/api/src/stockviz/settings.py` — fail-fast live-provider configuration.
- `apps/api/src/stockviz/workers/market_ingest_consumer.py` — optional non-blocking Massive shadow execution around the unchanged yfinance persistence result.
- `apps/api/src/stockviz/cli.py` — reproducible `market-shadow` command.
- `apps/api/src/stockviz/models/market.py` and a new Alembic revision — generic bar semantics and evidence-sized Decimal volume.
- `apps/api/src/stockviz/schemas.py`, recommendation/replay/trading adapters — Decimal-volume propagation.
- `apps/api/Dockerfile`, `infra/docker-compose.verify.yml`, and verification scripts — deterministic clean-build and optional live-provider workflows.
- `docs/MARKET_DATA.md`, setup/architecture guides, env examples, and agent guides — semantics, operation, licensing, and deferred India requirements.

---

### Task 1: Capture Baseline and Add Fail-Fast Provider Configuration

**Files:**
- Modify: `apps/api/src/stockviz/settings.py`
- Modify: `apps/api/tests/test_settings.py`
- Modify: `apps/api/.env.example`
- Modify: `infra/.env.example`
- Modify: `infra/docker-compose.yml`
- Create: `artifacts/verification/README.md`

**Interfaces:**
- Consumes: existing `Settings` model and Compose `infra/.env` interpolation.
- Produces: `Settings.massive_shadow_enabled: bool`, `massive_api_key: str`, `massive_shadow_lookback_days: int`, and resolved `news_provider: str`; startup validation for explicitly selected providers.

- [ ] **Step 1: Record the pre-change baseline without changing tests**

Run:

```powershell
uv --directory apps/api run pytest | Tee-Object artifacts/verification/api-baseline.txt
pnpm --filter @stockviz/web test | Tee-Object artifacts/verification/web-baseline.txt
```

Expected: record exact pass/fail/skip counts. Any failures present here are listed under “pre-existing unrelated failures” and are never hidden by later focused runs.

- [ ] **Step 2: Write failing settings tests**

Add tests that pin these behaviors:

```python
def test_massive_shadow_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="MASSIVE_API_KEY"):
        Settings(massive_shadow_enabled=True, massive_api_key="")


def test_massive_shadow_accepts_key() -> None:
    settings = Settings(massive_shadow_enabled=True, massive_api_key="private-test-key")
    assert settings.massive_shadow_enabled is True


def test_explicit_newsdata_provider_requires_key() -> None:
    with pytest.raises(ValidationError, match="NEWSDATA_KEY"):
        Settings(news_provider="newsdata", newsdata_key="")


def test_blank_news_provider_preserves_key_based_compatibility() -> None:
    assert Settings(news_provider="", newsdata_key="k").resolved_news_provider == "newsdata"
    assert Settings(news_provider="", newsdata_key="").resolved_news_provider == "none"


def test_explicit_anthropic_provider_requires_key() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(sentiment_provider="anthropic", anthropic_api_key="")


def test_explicit_http_sentiment_requires_url() -> None:
    with pytest.raises(ValidationError, match="SENTIMENT_SERVICE_URL"):
        Settings(sentiment_provider="http", sentiment_service_url="")
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_settings.py -v`

Expected: FAIL because Massive/news fields and conditional validation do not exist.

- [ ] **Step 4: Implement minimal settings validation**

Add fields and a property:

```python
massive_shadow_enabled: bool = False
massive_api_key: str = ""
massive_shadow_lookback_days: int = 90
news_provider: str = ""

@property
def resolved_news_provider(self) -> str:
    value = self.news_provider.strip().lower()
    if value:
        return value
    return "newsdata" if self.newsdata_key else "none"
```

Extend the existing `model_validator` after production-secret validation:

```python
if self.massive_shadow_enabled and not self.massive_api_key.strip():
    raise ValueError("MASSIVE_SHADOW_ENABLED requires MASSIVE_API_KEY")
if self.massive_shadow_lookback_days <= 0:
    raise ValueError("MASSIVE_SHADOW_LOOKBACK_DAYS must be > 0")
if self.resolved_news_provider not in {"none", "newsdata"}:
    raise ValueError("NEWS_PROVIDER must be none or newsdata")
if self.news_provider.strip().lower() == "newsdata" and not self.newsdata_key.strip():
    raise ValueError("NEWS_PROVIDER=newsdata requires NEWSDATA_KEY")
sentiment = self.sentiment_provider.strip().lower()
if sentiment == "anthropic" and not self.anthropic_api_key.strip():
    raise ValueError("SENTIMENT_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
if sentiment == "http" and not self.sentiment_service_url.strip():
    raise ValueError("SENTIMENT_PROVIDER=http requires SENTIMENT_SERVICE_URL")
```

- [ ] **Step 5: Pass config through Compose and document secrets**

Add only env interpolation—never values—to the API service:

```yaml
MASSIVE_SHADOW_ENABLED: ${MASSIVE_SHADOW_ENABLED:-false}
MASSIVE_API_KEY: ${MASSIVE_API_KEY:-}
MASSIVE_SHADOW_LOOKBACK_DAYS: ${MASSIVE_SHADOW_LOOKBACK_DAYS:-90}
NEWS_PROVIDER: ${NEWS_PROVIDER:-}
```

Document that `MASSIVE_API_KEY` and `NEWSDATA_KEY` belong in `infra/.env`, are never committed, and explicit provider selection fails startup without them.

- [ ] **Step 6: Verify GREEN and regression scope**

Run:

```powershell
uv --directory apps/api run pytest tests/test_settings.py tests/test_cli_news.py -v
uv --directory apps/api run ruff check src/stockviz/settings.py tests/test_settings.py
```

Expected: PASS with no lint errors.

- [ ] **Step 7: Commit**

```powershell
git add apps/api/src/stockviz/settings.py apps/api/tests/test_settings.py apps/api/.env.example infra/.env.example infra/docker-compose.yml artifacts/verification/README.md
git commit -m "feat(config): fail fast for selected live providers"
```

---

### Task 2: Define Canonical Bar Semantics and Exclude Incomplete Daily Bars

**Files:**
- Create: `apps/api/src/stockviz/services/ingest/bar_semantics.py`
- Modify: `apps/api/src/stockviz/services/ingest/prices.py`
- Modify: `apps/api/src/stockviz/services/ingest/backfill.py`
- Modify: `apps/api/src/stockviz/services/ingest/__init__.py`
- Modify: `apps/api/tests/test_ingest_prices.py`
- Modify: `apps/api/tests/test_ingest_seed.py`

**Interfaces:**
- Produces: `AdjustmentSemantics`, `SessionScope`, `session_label(value: date) -> datetime`, `new_york_session_date(value: datetime) -> date`, and generic `completed_daily_bars(bars: Sequence[TBar], now: datetime | None = None) -> list[TBar]`, where `TBar` is bound to a local protocol exposing `ts: datetime` and `interval: str`. `bar_semantics.py` does not import `BarRecord`, avoiding a circular import.
- Changes: `BarRecord.volume` becomes `Decimal`; adds `adjustment_semantics` and `session_scope`; no provider field is added.

- [ ] **Step 1: Write failing semantic and completion tests**

Cover DST-safe Massive timestamps, yfinance local-midnight labels, Decimal volume, and conservative completion:

```python
def test_session_label_is_naive_midnight() -> None:
    assert session_label(date(2025, 3, 10)) == datetime(2025, 3, 10)


def test_new_york_session_date_handles_dst() -> None:
    assert new_york_session_date(datetime(2025, 7, 1, 4, tzinfo=UTC)) == date(2025, 7, 1)
    assert new_york_session_date(datetime(2025, 1, 2, 5, tzinfo=UTC)) == date(2025, 1, 2)


def test_completed_daily_bars_excludes_same_new_york_date() -> None:
    now = datetime(2025, 7, 2, 22, tzinfo=UTC)
    bars = [_bar("2025-07-01"), _bar("2025-07-02")]
    assert [bar.ts.date() for bar in completed_daily_bars(bars, now=now)] == [date(2025, 7, 1)]


def test_yfinance_records_generic_semantics_and_decimal_volume() -> None:
    bar = fetch_yfinance_daily("AAPL", history_fn=lambda *_: _yf_fixture_df())[0]
    assert bar.volume == Decimal("50000000")
    assert bar.adjustment_semantics is AdjustmentSemantics.SPLIT_ADJUSTED
    assert bar.session_scope is SessionScope.REGULAR
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_ingest_prices.py -v`

Expected: import/type/attribute failures for the new semantics.

- [ ] **Step 3: Implement the generic semantic module**

```python
class AdjustmentSemantics(StrEnum):
    UNADJUSTED = "unadjusted"
    SPLIT_ADJUSTED = "split_adjusted"
    SPLIT_DIVIDEND_ADJUSTED = "split_dividend_adjusted"


class SessionScope(StrEnum):
    REGULAR = "regular"
    PROVIDER_DAILY = "provider_daily"


NEW_YORK = ZoneInfo("America/New_York")


def session_label(value: date) -> datetime:
    return datetime.combine(value, time.min)


def new_york_session_date(value: datetime) -> date:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(NEW_YORK).date()
```

Implement `completed_daily_bars` using `now or datetime.now(UTC)`, retaining non-daily bars and daily bars whose `bar.ts.date()` is strictly before the current New York date.

- [ ] **Step 4: Update every `BarRecord` producer**

Use `Decimal(str(row["Volume"]))`, `SPLIT_ADJUSTED`, and `REGULAR` for yfinance. Use `Decimal(row["5. volume"])`, `UNADJUSTED`, and `REGULAR` for the existing Alpha Vantage `TIME_SERIES_DAILY` endpoint unless its contract is changed. Mark CSV backfill rows explicitly according to their documented v1 semantics rather than inheriting a default.

Call `completed_daily_bars()` in `fetch_daily_bars()` immediately before return so both CLI and Kafka persistence reject incomplete same-day daily bars.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
uv --directory apps/api run pytest tests/test_ingest_prices.py tests/test_ingest_seed.py tests/test_market_news_pipeline.py -v
uv --directory apps/api run ruff check src/stockviz/services/ingest tests/test_ingest_prices.py
```

Expected: PASS. Existing provider ordering and fallback tests remain unchanged.

- [ ] **Step 6: Commit**

```powershell
git add apps/api/src/stockviz/services/ingest apps/api/tests/test_ingest_prices.py apps/api/tests/test_ingest_seed.py apps/api/tests/test_market_news_pipeline.py
git commit -m "feat(market): define canonical daily bar semantics"
```

---

### Task 3: Implement the Massive Provider Adapter

**Files:**
- Create: `apps/api/src/stockviz/services/ingest/providers/__init__.py`
- Create: `apps/api/src/stockviz/services/ingest/providers/massive.py`
- Create: `apps/api/tests/test_massive_provider.py`

**Interfaces:**
- Consumes: canonical `BarRecord`, `AdjustmentSemantics`, `SessionScope`, and `httpx`.
- Produces: `fetch_massive_daily(ticker: str, *, start: date, end: date, api_key: str, get_fn: MassiveGetFn = _default_get) -> list[BarRecord]`, `fetch_massive_splits(ticker: str, *, start: date, end: date, api_key: str, get_fn: MassiveGetFn = _default_get) -> list[MassiveAction]`, `fetch_massive_dividends(ticker: str, *, start: date, end: date, api_key: str, get_fn: MassiveGetFn = _default_get) -> list[MassiveAction]`, and `fetch_massive_open_close(ticker: str, *, session_date: date, api_key: str, get_fn: MassiveGetFn = _default_get) -> MassiveOpenClose`; provider-only types remain in this module.

- [ ] **Step 1: Write fixture-first failing adapter tests**

Use a fake HTTP callable and assert:

```python
def test_massive_daily_maps_decimal_values_and_et_session_date() -> None:
    bars = fetch_massive_daily(
        "AAPL",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        api_key="secret",
        get_fn=_fake_pages(MASSIVE_AGGS_OK),
    )
    assert bars[0].ticker == "AAPL"
    assert bars[0].ts == datetime(2025, 1, 2)
    assert bars[0].volume == Decimal("25933.6")
    assert bars[0].source == "massive"
    assert bars[0].adjustment_semantics is AdjustmentSemantics.SPLIT_ADJUSTED
    assert bars[0].session_scope is SessionScope.PROVIDER_DAILY


def test_massive_daily_follows_next_url_without_leaking_key() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    bars = fetch_massive_daily(
        "AAPL",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        api_key="secret",
        get_fn=_recording_pages(calls),
    )
    assert len(bars) == 2
    assert all("apiKey" not in url for url, _headers in calls)
    assert all(headers["Authorization"] == "Bearer secret" for _url, headers in calls)


def test_massive_daily_rejects_unadjusted_response() -> None:
    with pytest.raises(MassiveSemanticError, match="adjusted"):
        fetch_massive_daily(
            "AAPL",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            api_key="secret",
            get_fn=_fake_pages({"adjusted": False, "results": []}),
        )
```

Also test HTTP errors, provider `ERROR` status, malformed rows, negative volume, split/dividend parsing, and the per-date open/close payload.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_massive_provider.py -v`

Expected: FAIL because the provider package does not exist.

- [ ] **Step 3: Implement exact Decimal JSON parsing and authenticated pagination**

The default getter must send the configured key in the `Authorization: Bearer` header, call `raise_for_status()`, and decode using:

```python
json.loads(response.content, parse_float=Decimal, parse_int=Decimal)
```

The aggregates request is:

```text
GET https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
adjusted=true&sort=asc&limit=50000
```

Convert `t` from Unix milliseconds to aware UTC, then to a New York session date, then to the canonical naive-midnight label. Do not retain `request_id` or a Massive response object in `BarRecord`.

- [ ] **Step 4: Implement action and open/close probes**

Use current endpoints `/stocks/v1/splits`, `/stocks/v1/dividends`, and `/v1/open-close/{ticker}/{date}`. Provider action IDs remain private fields on `MassiveAction`; the generic comparison layer receives only action kind/date and not the ID.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
uv --directory apps/api run pytest tests/test_massive_provider.py -v
uv --directory apps/api run ruff check src/stockviz/services/ingest/providers tests/test_massive_provider.py
```

Expected: PASS without a real API key or network call.

- [ ] **Step 6: Commit**

```powershell
git add apps/api/src/stockviz/services/ingest/providers apps/api/tests/test_massive_provider.py
git commit -m "feat(market): add isolated Massive daily-bar adapter"
```

---

### Task 4: Build Quantified Shadow Comparison and Precision Audit

**Files:**
- Create: `apps/api/src/stockviz/services/ingest/shadow.py`
- Create: `apps/api/tests/test_market_shadow_comparison.py`

**Interfaces:**
- Produces: `compare_symbol(reference, candidate, *, actions, raw_latest) -> SymbolComparison`, `audit_volume_precision(bars) -> VolumePrecisionAudit`, and JSON-safe `as_dict()` methods.
- Consumes: generic `BarRecord` lists and generic `ActionWindow(kind, effective_date)` values only.

- [ ] **Step 1: Write failing statistical tests with hand-calculable fixtures**

Pin session joins, missing/extra dates, newest raw/completed bars, basis-point thresholds, volume thresholds, quantiles, action windows, and classifications:

```python
def test_compare_symbol_quantifies_sessions_and_errors() -> None:
    result = compare_symbol(_reference(), _candidate(), actions=[])
    assert result.common_sessions == 3
    assert result.reference_only_sessions == [date(2025, 1, 3)]
    assert result.candidate_only_sessions == [date(2025, 1, 6)]
    assert result.fields["close"].over_10_bps == 1
    assert result.volume.over_1_percent == 1


def test_action_window_statistics_are_separate() -> None:
    result = compare_symbol(
        _reference(),
        _candidate(),
        actions=[ActionWindow("split", date(2025, 1, 6))],
    )
    assert result.corporate_action_sessions > 0
    assert result.ordinary_sessions + result.corporate_action_sessions == result.common_sessions


def test_volume_precision_preserves_provider_exponent() -> None:
    audit = audit_volume_precision([_bar(volume="10"), _bar(volume="25933.6000")])
    assert audit.maximum_fractional_digits == 4
    assert audit.scale_counts == {0: 1, 4: 1}
    assert audit.recommended_precision == 23
    assert audit.recommended_scale == 4
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_market_shadow_comparison.py -v`

Expected: FAIL because comparison functions do not exist.

- [ ] **Step 3: Implement deterministic statistics**

Use `Decimal` for differences and relative error. Define relative error as `abs(candidate-reference) / abs(reference)` and return `None` when reference is zero. Quantiles use nearest-rank over sorted values so fixture results are reproducible without adding a statistics dependency. Store threshold counts explicitly at the approved price and volume levels.

Build action windows by selecting the two joined sessions before, the effective session when present, and two joined sessions after. Never alter input values based on classification.

- [ ] **Step 4: Implement precision audit formula**

For each Decimal volume, fractional digits are `max(0, -value.as_tuple().exponent)`. Whole-number digits preserve the existing signed-BigInteger capacity. Return:

```python
recommended_scale = maximum_fractional_digits
recommended_precision = 19 + recommended_scale
```

Record max-scale symbols/sessions and counts by scale. Do not normalize Decimal exponents before measuring.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
uv --directory apps/api run pytest tests/test_market_shadow_comparison.py -v
uv --directory apps/api run ruff check src/stockviz/services/ingest/shadow.py tests/test_market_shadow_comparison.py
```

Expected: PASS with exact fixture statistics.

- [ ] **Step 6: Commit**

```powershell
git add apps/api/src/stockviz/services/ingest/shadow.py apps/api/tests/test_market_shadow_comparison.py
git commit -m "feat(market): quantify provider shadow mismatches"
```

---

### Task 5: Add Private JSON/Markdown Reports and the Comparison CLI

**Files:**
- Create: `apps/api/src/stockviz/services/ingest/shadow_report.py`
- Create: `apps/api/tests/test_shadow_report.py`
- Create: `apps/api/tests/test_cli_market_shadow.py`
- Modify: `apps/api/src/stockviz/cli.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `write_shadow_report(run, output_dir) -> tuple[Path, Path]` and CLI `python -m stockviz.cli market-shadow TICKER --from YYYY-MM-DD --to YYYY-MM-DD --output-dir PATH` (the positional ticker argument uses `nargs="*"`).
- Default symbols: `AAPL MSFT NVDA AMZN META TSLA JPM`; precision probes also include `C GE AIG`.

- [ ] **Step 1: Write failing report serialization tests**

Assert JSON contains per-symbol raw counts/statistics but not API keys, and Markdown includes architecture/config, canonical semantics, methodology, per-symbol table, corporate actions, session-scope findings, tests, clean verification, blockers, licensing gate, and cutover recommendation sections.

```python
def test_report_writes_json_and_markdown_without_credentials(tmp_path: Path) -> None:
    json_path, md_path = write_shadow_report(_run(), tmp_path)
    assert json.loads(json_path.read_text())["symbols"]["AAPL"]["common_sessions"] == 3
    markdown = md_path.read_text()
    assert "| AAPL |" in markdown
    assert "Production/commercial licensing gate" in markdown
    assert "secret" not in json_path.read_text() + markdown
```

- [ ] **Step 2: Write failing CLI tests**

Patch the runner—not `httpx` internals—and assert missing Massive key exits 2, invalid ranges exit 2, default symbols are present, paths print to stdout, and no database write function is called.

- [ ] **Step 3: Run tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_shadow_report.py tests/test_cli_market_shadow.py -v`

Expected: FAIL because report/CLI functions do not exist.

- [ ] **Step 4: Implement private report writing**

Default output is `artifacts/private/massive-shadow/` plus a child directory named by `datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")`. Add `artifacts/private/` to `.gitignore`. Use `Path.mkdir(parents=True, exist_ok=False)`, JSON with Decimal/date/datetime conversion, and atomic temporary-file replacement within the output directory.

The report states technical and licensing gates separately and reports `not_evaluated` rather than a positive recommendation when live evidence is absent.

- [ ] **Step 5: Implement CLI orchestration**

The command independently fetches yfinance and Massive, calls the action endpoints, samples Massive open/close dates, invokes `compare_symbol`, aggregates precision, and writes reports. It never opens a SQLModel `Session` and never imports a router/API module.

CLI defaults:

```text
symbols: AAPL MSFT NVDA AMZN META TSLA JPM
from: five years before today, bounded by subscription response
to: today
output: artifacts/private/massive-shadow
```

Pass the API key only in memory. Do not print request URLs containing credentials.

- [ ] **Step 6: Verify GREEN**

Run:

```powershell
uv --directory apps/api run pytest tests/test_shadow_report.py tests/test_cli_market_shadow.py -v
uv --directory apps/api run python -m stockviz.cli market-shadow --help
git check-ignore artifacts/private/example.json
```

Expected: tests PASS, help lists range/output arguments, and the private artifact path is ignored.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore apps/api/src/stockviz/cli.py apps/api/src/stockviz/services/ingest/shadow_report.py apps/api/tests/test_shadow_report.py apps/api/tests/test_cli_market_shadow.py
git commit -m "feat(market): add private Massive shadow reports"
```

---

### Task 6: Add Non-Persistent Operational Shadow Execution

**Files:**
- Modify: `apps/api/src/stockviz/workers/market_ingest_consumer.py`
- Create: `apps/api/tests/test_market_shadow_worker.py`
- Modify: `apps/api/tests/test_market_news_pipeline.py`

**Interfaces:**
- Produces: `run_massive_shadow(ticker, reference_bars, *, since, settings) -> SymbolComparison | None`.
- Preserves: `fetch_bars_for_event(event) -> list[BarRecord]` and `persist_market_refresh()` receive only yfinance/default bars.

- [ ] **Step 1: Write failing worker tests**

```python
def test_shadow_disabled_never_calls_massive(monkeypatch) -> None:
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_massive_daily",
        _fail_if_called,
    )
    assert run_massive_shadow("AAPL", _bars(), since=None, settings=_settings(False)) is None


def test_shadow_result_is_not_returned_for_persistence(monkeypatch) -> None:
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_massive_daily",
        lambda **_: _massive_bars(),
    )
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.get_settings",
        lambda: _settings(True),
    )
    primary = fetch_bars_for_event(_event())
    assert {bar.source for bar in primary} == {"yfinance"}


def test_runtime_shadow_failure_logs_error_but_keeps_primary(caplog, monkeypatch) -> None:
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.fetch_massive_daily",
        _raise_timeout,
    )
    monkeypatch.setattr(
        "stockviz.workers.market_ingest_consumer.get_settings",
        lambda: _settings(True),
    )
    primary = fetch_bars_for_event(_event())
    assert primary
    assert "Massive shadow failed" in caplog.text
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_market_shadow_worker.py -v`

Expected: FAIL because the shadow runner does not exist.

- [ ] **Step 3: Implement bounded shadow execution**

Use `max(payload.since.date(), today-lookback)` when `since` exists, otherwise `today-lookback`. Log one structured JSON summary per ticker. Catch Massive network/provider/semantic exceptions only around shadow work; do not catch settings validation and do not change the primary bar list.

- [ ] **Step 4: Verify GREEN and event regression**

Run:

```powershell
uv --directory apps/api run pytest tests/test_market_shadow_worker.py tests/test_market_news_pipeline.py tests/test_scheduler_worker.py -v
uv --directory apps/api run ruff check src/stockviz/workers/market_ingest_consumer.py tests/test_market_shadow_worker.py
```

Expected: PASS; yfinance bars remain the only `persist_market_refresh` input.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/stockviz/workers/market_ingest_consumer.py apps/api/tests/test_market_shadow_worker.py apps/api/tests/test_market_news_pipeline.py
git commit -m "feat(market): run Massive as a non-persistent shadow"
```

---

### Task 7: Run the Live Precision Gate, Then Migrate Generic Bar Semantics and Volume

**Files:**
- Modify: `apps/api/src/stockviz/models/market.py`
- Create: `apps/api/migrations/versions/f8a6c2d4e901_price_bar_semantics_decimal_volume.py`
- Modify: `apps/api/src/stockviz/schemas.py`
- Modify: `apps/api/src/stockviz/services/recommend/engine.py`
- Modify: `apps/api/src/stockviz/services/replay/market.py`
- Modify: `apps/api/src/stockviz/services/trading/simulation_adapter.py`
- Modify: `apps/api/tests/test_ingest_prices.py`
- Modify: `apps/api/tests/test_recommend.py`
- Modify: `apps/api/tests/test_replay_router.py`
- Modify: `apps/api/tests/test_routers.py`
- Modify: generated web API schema/types if OpenAPI generation changes them.

**Interfaces:**
- Consumes: private live report `volume_precision.recommended_precision` and `.recommended_scale`.
- Produces: `PriceBar.volume: Decimal`, `adjustment_semantics: str`, `session_scope: str`, and matching API/recommendation types.

- [ ] **Step 1: Execute the credential gate**

Run locally after placing `MASSIVE_API_KEY` in `infra/.env`. Load it into the child process without printing it, and remove it from the process environment afterward:

```powershell
$massiveLine = Get-Content -LiteralPath infra/.env | Where-Object { $_.StartsWith('MASSIVE_API_KEY=') } | Select-Object -First 1
if (-not $massiveLine -or -not $massiveLine.Substring('MASSIVE_API_KEY='.Length)) { throw 'MASSIVE_API_KEY is required' }
$env:MASSIVE_API_KEY = $massiveLine.Substring('MASSIVE_API_KEY='.Length)
try {
  uv --directory apps/api run python -m stockviz.cli market-shadow AAPL MSFT NVDA AMZN META TSLA JPM C GE AIG --from 2016-01-01 --to 2026-08-29 --output-dir artifacts/private/massive-shadow/precision-gate
} finally {
  Remove-Item Env:\MASSIVE_API_KEY -ErrorAction SilentlyContinue
}
```

Expected: private JSON report prints `recommended_scale=S` and `recommended_precision=19+S`. If the key is absent, the command exits 2. Stop this task and report the migration blocked; do not choose a scale from fixtures.

- [ ] **Step 2: Write failing Decimal-volume persistence/API tests using the observed scale**

Use a fractional value with exactly `S` digits and assert round-trip equality through SQLite/Postgres and JSON numeric serialization. Add a rejection test using `S+1` fractional digits so persistence fails loudly rather than rounding.

Update recommendation fixtures to accept `list[tuple[Decimal, Decimal]]` and prove the volume-above-mean vote is unchanged for integer inputs and correct for fractional inputs.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```powershell
uv --directory apps/api run pytest tests/test_ingest_prices.py tests/test_recommend.py tests/test_routers.py tests/test_replay_router.py -v
```

Expected: FAIL because `BigInteger`/`int` schemas cannot preserve the fractional fixture.

- [ ] **Step 4: Implement the evidence-sized model and migration**

Set constants in `models/market.py` to the exact report values:

```python
PRICE_BAR_VOLUME_SCALE = S
PRICE_BAR_VOLUME_PRECISION = 19 + PRICE_BAR_VOLUME_SCALE
```

Use `Numeric(PRICE_BAR_VOLUME_PRECISION, PRICE_BAR_VOLUME_SCALE)` and add non-null `adjustment_semantics` and `session_scope` fields. The Alembic upgrade:

1. adds both semantic columns with temporary server defaults `split_adjusted` and `regular`;
2. alters volume from `BIGINT` to `NUMERIC(P, S)` using `volume::numeric(P,S)`;
3. removes semantic server defaults after existing rows are backfilled.

The downgrade refuses if fractional volume exists, with a clear exception, instead of truncating it to `BIGINT`.

- [ ] **Step 5: Propagate Decimal without changing the web numeric contract**

Change `BarOut.volume` and `ReplayBarOut.volume` to Decimal and update recommendation tuples to `(Decimal, Decimal)`. Remove redundant `Decimal(bar.volume)` conversions. Add response assertions proving FastAPI emits a JSON number accepted by the existing TypeScript `number` contract; regenerate schema only if the OpenAPI shape changes.

- [ ] **Step 6: Apply and test the migration on PostgreSQL**

Run:

```powershell
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run pytest tests/test_ingest_prices.py tests/test_recommend.py tests/test_routers.py tests/test_replay_router.py tests/test_market_kernel_integration.py -v
uv --directory apps/api run alembic heads
```

Expected: migration succeeds, focused tests PASS, and the sole head is `f8a6c2d4e901`.

- [ ] **Step 7: Commit**

```powershell
git add apps/api/src/stockviz/models/market.py apps/api/migrations/versions/f8a6c2d4e901_price_bar_semantics_decimal_volume.py apps/api/src/stockviz/schemas.py apps/api/src/stockviz/services/recommend/engine.py apps/api/src/stockviz/services/replay/market.py apps/api/src/stockviz/services/trading/simulation_adapter.py apps/api/tests apps/web/lib/api
git commit -m "feat(market): persist bar semantics and exact adjusted volume"
```

---

### Task 8: Add Credential-Free Clean Build Verification

**Files:**
- Modify: `apps/api/Dockerfile`
- Create: `infra/docker-compose.verify.yml`
- Create: `scripts/verify-pipeline-clean.ps1`
- Create: `apps/api/tests/test_docker_verification_layout.py`
- Modify: `package.json`

**Interfaces:**
- Produces: `pnpm verify:pipeline:clean`, requiring Docker but no provider credentials.
- Isolation: project `stockviz-pipeline-verify`, distinct containers/ports/network, volume `stockviz_pipeline_verify_postgres_data`.

- [ ] **Step 1: Write failing layout tests**

Parse the Dockerfile/Compose/script as text and assert:

```python
def test_clean_verification_builds_api_and_web_from_source() -> None:
    compose = VERIFY_COMPOSE.read_text()
    script = VERIFY_SCRIPT.read_text()
    assert "target: test" in compose
    assert "build --no-cache api web api-tests" in script
    assert "stockviz_pipeline_verify_postgres_data" in compose
    assert "MASSIVE_API_KEY" not in compose


def test_clean_verification_runs_market_news_kafka_paths() -> None:
    script = VERIFY_SCRIPT.read_text()
    for test in ("test_market_event_pipeline_roundtrip", "test_news_sentiment_event_pipeline_roundtrip"):
        assert test in script
```

- [ ] **Step 2: Run layout tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_docker_verification_layout.py -v`

Expected: FAIL because verification files/target do not exist.

- [ ] **Step 3: Add an API test image target**

Derive `test` from the builder, install dev dependencies from the same lockfile, copy `tests`, and set pytest as its command. Do not change the production runtime stage contents or command.

- [ ] **Step 4: Add isolated verification Compose**

Override container names and ports (`15434`, `19092`, `18000`, `13100`), set the isolated Postgres volume name, and add `api-tests` using the Dockerfile `test` target with PostgreSQL/Kafka service URLs. The API/web services still use their production runtime targets.

- [ ] **Step 5: Implement the deterministic script**

The PowerShell script:

1. resolves and validates paths under the repository root;
2. runs `docker compose -p stockviz-pipeline-verify -f infra/docker-compose.yml -f infra/docker-compose.verify.yml down --volumes --remove-orphans` only for project `stockviz-pipeline-verify`;
3. runs `build --no-cache api web api-tests`;
4. starts Postgres, Kafka, topic init, API, and web;
5. runs deterministic settings/market/news/outbox tests and the PostgreSQL+Kafka market/news roundtrips inside `api-tests`;
6. checks API `/live` and web `/api/health`;
7. records `docker image inspect` IDs and test output under `artifacts/verification/`;
8. always tears down the isolated project and its volume in `finally`.

- [ ] **Step 6: Verify layout GREEN, then run the clean workflow**

Run:

```powershell
uv --directory apps/api run pytest tests/test_docker_verification_layout.py -v
pnpm verify:pipeline:clean
```

Expected: layout tests PASS; both images build from source; deterministic market/news/event tests pass; API/web health checks return 200; isolated resources are removed.

- [ ] **Step 7: Commit**

```powershell
git add apps/api/Dockerfile infra/docker-compose.verify.yml scripts/verify-pipeline-clean.ps1 apps/api/tests/test_docker_verification_layout.py package.json
git commit -m "test(docker): reproduce pipeline activation from clean images"
```

---

### Task 9: Add Optional Private Live-Provider Verification

**Files:**
- Create: `scripts/verify-providers-live.ps1`
- Create: `apps/api/tests/test_live_provider_script.py`
- Modify: `infra/docker-compose.verify.yml`
- Modify: `package.json`

**Interfaces:**
- Produces: `pnpm verify:providers:live` and private artifacts mounted at `/private-artifacts`.
- Requires: explicit `MASSIVE_SHADOW_ENABLED=true`/`NEWS_PROVIDER=newsdata` selections and matching keys in `infra/.env`.

- [ ] **Step 1: Write failing script contract tests**

Assert the script checks selections before Docker calls, never prints secret values, uses rebuilt `stockviz-api:verify`, mounts only the private artifact directory, and invokes `ingest`, `news`, and `market-shadow` commands.

- [ ] **Step 2: Run tests and verify RED**

Run: `uv --directory apps/api run pytest tests/test_live_provider_script.py -v`

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Implement fail-fast local workflow**

Parse only variable presence from `infra/.env`; do not echo values. Rules:

```text
MASSIVE_SHADOW_ENABLED=true -> MASSIVE_API_KEY must be non-empty
NEWS_PROVIDER=newsdata -> NEWSDATA_KEY must be non-empty
SENTIMENT_PROVIDER=anthropic -> ANTHROPIC_API_KEY must be non-empty
SENTIMENT_PROVIDER=http -> SENTIMENT_SERVICE_URL must be non-empty
```

Run all commands through the rebuilt API image on the isolated network. Write output beneath `artifacts/private/live-verification/<UTC-run-id>`. Do not start a Massive-backed API path and do not copy artifacts into either image.

- [ ] **Step 4: Verify GREEN and missing-key behavior**

Run:

```powershell
uv --directory apps/api run pytest tests/test_live_provider_script.py -v
pnpm verify:providers:live
```

Expected without configured keys: non-zero exit naming missing variable, before provider/Docker execution. Expected with locally configured keys: yfinance ingest, selected news ingest, and Massive comparison run from the rebuilt image with private output paths.

- [ ] **Step 5: Commit**

```powershell
git add scripts/verify-providers-live.ps1 apps/api/tests/test_live_provider_script.py infra/docker-compose.verify.yml package.json
git commit -m "test(market): add private live-provider verification"
```

---

### Task 10: Document Semantics, India Requirements, Evidence, and Gates

**Files:**
- Create: `docs/MARKET_DATA.md`
- Modify: `docs/EVENT_DRIVEN_ARCHITECTURE.md`
- Modify: `docs/SETUP.md`
- Modify: `docs/KNOWN_LIMITATIONS.md`
- Modify: `CLAUDE.md`
- Modify: `apps/api/CLAUDE.md`
- Modify: `README.md`
- Create: `apps/api/tests/test_market_data_docs.py`

**Interfaces:**
- Produces: public methodology/operations documentation without private Massive-derived values; private Markdown report remains the detailed final evidence artifact.

- [ ] **Step 1: Write failing documentation tests**

Assert `docs/MARKET_DATA.md` contains canonical semantics, Massive/yfinance adapter boundaries, ordinary/action mismatch methodology, source/adjustment/session provenance, completed-bar rules, deterministic/live commands, private artifact policy, separate technical/licensing gates, and all deferred India requirements.

- [ ] **Step 2: Run docs test and verify RED**

Run: `uv --directory apps/api run pytest tests/test_market_data_docs.py -v`

Expected: FAIL because `docs/MARKET_DATA.md` does not exist.

- [ ] **Step 3: Write public documentation without publishing private data**

Document:

- architecture and config changes;
- canonical bar semantics and source/adjustment/session fields;
- provider adapter and shadow methodology;
- how to read the private per-symbol JSON/Markdown report;
- corporate-action/session-scope classifications;
- deterministic and optional live verification;
- licensing assumption and separate gates;
- no-cutover status;
- canonical exchange-qualified symbols, provider instrument IDs, INR, NSE/BSE calendars, and mixed-currency portfolio work deferred to a future milestone.

Do not paste Massive response rows or private mismatch values into committed docs.

- [ ] **Step 4: Verify docs GREEN**

Run:

```powershell
uv --directory apps/api run pytest tests/test_market_data_docs.py -v
pnpm exec prettier --check docs/MARKET_DATA.md docs/EVENT_DRIVEN_ARCHITECTURE.md docs/SETUP.md docs/KNOWN_LIMITATIONS.md README.md CLAUDE.md apps/api/CLAUDE.md
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add docs README.md CLAUDE.md apps/api/CLAUDE.md apps/api/tests/test_market_data_docs.py
git commit -m "docs: define market-data semantics and cutover gates"
```

---

### Task 11: Full Verification and Final Private Report

**Files:**
- Update locally only: `artifacts/private/massive-shadow/*/report.json`
- Update locally only: `artifacts/private/massive-shadow/*/report.md`
- Update locally only: `artifacts/verification/*`

**Interfaces:**
- Produces: fresh evidence for every completion claim and a cutover recommendation with separate technical/licensing outcomes.

- [ ] **Step 1: Run focused provider and pipeline suites**

```powershell
uv --directory apps/api run pytest tests/test_settings.py tests/test_ingest_prices.py tests/test_massive_provider.py tests/test_market_shadow_comparison.py tests/test_shadow_report.py tests/test_cli_market_shadow.py tests/test_market_shadow_worker.py tests/test_market_news_pipeline.py tests/test_kafka_integration.py -v
```

Expected: PASS; Kafka tests use the verification broker or are explicitly run with `STOCKVIZ_KAFKA_REQUIRED=1` in Compose.

- [ ] **Step 2: Run complete repository quality gates**

```powershell
pnpm lint
pnpm typecheck
pnpm build
pnpm --filter @stockviz/web test
uv --directory apps/api run pytest
```

Expected: zero new failures. Compare any failures against Task 1 baseline and list unrelated pre-existing failures separately.

- [ ] **Step 3: Run clean deterministic containers**

Run: `pnpm verify:pipeline:clean`

Expected: source rebuilds, migrations, deterministic market/news/Kafka paths, and API/web health checks pass from isolated resources.

- [ ] **Step 4: Run optional live-provider evidence when credentials exist**

Run:

```powershell
pnpm verify:providers:live
```

Expected with credentials: private report covers AAPL, MSFT, NVDA, AMZN, META, TSLA, JPM plus precision probes; session-scope samples and corporate-action windows are present. Without credentials: fail-fast evidence names missing variables and the technical gate remains `not_evaluated`.

- [ ] **Step 5: Audit requirements against fresh evidence**

Check every completion criterion in the spec. The private report must include architecture/config, canonical semantics, adapter design, methodology, per-symbol mismatch statistics, action findings, tests, clean-container evidence, blockers/licensing assumptions, and separate technical/licensing recommendations.

- [ ] **Step 6: Verify repository cleanliness and no private data leakage**

```powershell
git status --short
git diff --check
git ls-files artifacts/private
rg -n "MASSIVE_API_KEY=.*[^=[:space:]]|NEWSDATA_KEY=.*[^=[:space:]]" . -g '!infra/.env' -g '!apps/api/.env'
```

Expected: no tracked private artifacts, no secrets, no whitespace errors, and only intentional source/document changes.

- [ ] **Step 7: Final commit if verification caused tracked documentation corrections**

```powershell
git add docs/MARKET_DATA.md docs/EVENT_DRIVEN_ARCHITECTURE.md docs/SETUP.md docs/KNOWN_LIMITATIONS.md README.md CLAUDE.md apps/api/CLAUDE.md
git commit -m "chore: finalize Massive shadow verification evidence"
```

Do not commit private reports or secrets.
