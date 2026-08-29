"""Fixture-only contract tests for the private Massive adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.providers.massive import (
    MassiveProviderError,
    MassiveSemanticError,
    _default_get,
    fetch_massive_daily,
    fetch_massive_dividends,
    fetch_massive_minutes,
    fetch_massive_open_close,
    fetch_massive_splits,
    reconstruct_massive_session,
)

GetFn = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]


def _millis(value: str) -> Decimal:
    return Decimal(int(datetime.fromisoformat(value).timestamp() * 1000))


MASSIVE_AGGS_OK = {
    "adjusted": True,
    "status": "OK",
    "request_id": "provider-only-id",
    "results": [
        {
            "o": Decimal("242.70"),
            "h": Decimal("244.18"),
            "l": Decimal("241.89"),
            "c": Decimal("243.85"),
            "v": Decimal("25933.6000"),
            "t": _millis("2025-01-02T05:00:00+00:00"),
        }
    ],
}


def _fake_pages(*payloads: dict[str, Any]) -> GetFn:
    remaining = iter(payloads)

    def get(_url: str, _params: dict[str, str], _headers: dict[str, str]) -> dict[str, Any]:
        return next(remaining)

    return get


def test_default_get_decodes_json_numbers_directly_to_decimal(monkeypatch) -> None:
    response = httpx.Response(
        200,
        content=b'{"whole": 12, "fractional": 25933.6000}',
        request=httpx.Request("GET", "https://api.massive.com/test"),
    )
    monkeypatch.setattr(httpx, "get", lambda *_args, **_kwargs: response)

    payload = _default_get(
        "https://api.massive.com/test",
        {"adjusted": "true"},
        {"Authorization": "Bearer secret"},
    )

    assert payload == {"whole": Decimal("12"), "fractional": Decimal("25933.6000")}


def test_massive_daily_maps_decimal_values_and_new_york_session_date() -> None:
    bars = fetch_massive_daily(
        "aapl",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        api_key="secret",
        get_fn=_fake_pages(MASSIVE_AGGS_OK),
    )

    assert len(bars) == 1
    bar = bars[0]
    assert bar.ticker == "AAPL"
    assert bar.ts == datetime(2025, 1, 2)
    assert bar.volume == Decimal("25933.6000")
    assert bar.source == "massive"
    assert bar.adjustment_semantics is AdjustmentSemantics.SPLIT_ADJUSTED
    assert bar.session_scope is SessionScope.PROVIDER_DAILY
    assert not hasattr(bar, "request_id")


def test_massive_daily_handles_dst_session_timestamp() -> None:
    payload = {
        **MASSIVE_AGGS_OK,
        "results": [{**MASSIVE_AGGS_OK["results"][0], "t": _millis("2025-07-01T04:00:00Z")}],
    }

    bar = fetch_massive_daily(
        "AAPL",
        start=date(2025, 7, 1),
        end=date(2025, 7, 1),
        api_key="secret",
        get_fn=_fake_pages(payload),
    )[0]

    assert bar.ts == datetime(2025, 7, 1)


def test_massive_daily_follows_sanitized_next_url_with_bearer_auth() -> None:
    calls: list[tuple[str, dict[str, str], dict[str, str]]] = []
    first = {
        **MASSIVE_AGGS_OK,
        "next_url": "https://api.massive.com/v2/aggs/next?cursor=abc&apiKey=echoed-key",
    }
    second = {
        **MASSIVE_AGGS_OK,
        "results": [{**MASSIVE_AGGS_OK["results"][0], "t": _millis("2025-01-03T05:00:00Z")}],
    }
    pages = iter((first, second))

    def recording_get(url: str, params: dict[str, str], headers: dict[str, str]) -> dict[str, Any]:
        calls.append((url, params, headers))
        return next(pages)

    bars = fetch_massive_daily(
        "AAPL",
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        api_key="secret",
        get_fn=recording_get,
    )

    assert len(bars) == 2
    assert all("apikey" not in url.lower() for url, _params, _headers in calls)
    assert all("apikey" not in {key.lower() for key in params} for _url, params, _headers in calls)
    assert all(headers["Authorization"] == "Bearer secret" for _url, _params, headers in calls)
    assert calls[0][1]["adjusted"] == "true"


def test_massive_daily_rejects_unadjusted_response() -> None:
    with pytest.raises(MassiveSemanticError, match="adjusted"):
        fetch_massive_daily(
            "AAPL",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            api_key="secret",
            get_fn=_fake_pages({"adjusted": False, "status": "OK", "results": []}),
        )


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"adjusted": True, "status": "ERROR", "error": "not entitled"}, "not entitled"),
        ({"adjusted": True, "status": "OK", "results": [{"o": 1}]}, "malformed"),
        (
            {
                **MASSIVE_AGGS_OK,
                "results": [{**MASSIVE_AGGS_OK["results"][0], "v": Decimal("-1")}],
            },
            "volume",
        ),
    ],
)
def test_massive_daily_rejects_provider_and_semantic_errors(payload, message) -> None:
    error_type = MassiveProviderError if payload.get("status") == "ERROR" else MassiveSemanticError
    with pytest.raises(error_type, match=message):
        fetch_massive_daily(
            "AAPL",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            api_key="secret",
            get_fn=_fake_pages(payload),
        )


def test_massive_daily_wraps_http_error() -> None:
    response = httpx.Response(
        403,
        request=httpx.Request("GET", "https://api.massive.com/v2/aggs/test"),
    )

    def fail(*_args) -> dict[str, Any]:
        raise httpx.HTTPStatusError("forbidden", request=response.request, response=response)

    with pytest.raises(MassiveProviderError, match="HTTP 403"):
        fetch_massive_daily(
            "AAPL",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            api_key="secret",
            get_fn=fail,
        )


def test_massive_daily_requires_private_credential() -> None:
    with pytest.raises(ValueError, match="MASSIVE_API_KEY"):
        fetch_massive_daily(
            "AAPL",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            api_key="",
            get_fn=_fake_pages(MASSIVE_AGGS_OK),
        )


def test_massive_action_endpoints_keep_provider_ids_inside_adapter() -> None:
    split_payload = {
        "status": "OK",
        "results": [
            {
                "id": "split-id",
                "ticker": "NVDA",
                "execution_date": "2024-06-10",
                "split_from": Decimal("1"),
                "split_to": Decimal("10"),
            }
        ],
    }
    dividend_payload = {
        "status": "OK",
        "results": [
            {
                "id": "dividend-id",
                "ticker": "AAPL",
                "ex_dividend_date": "2025-02-10",
                "cash_amount": Decimal("0.25"),
                "currency": "USD",
            }
        ],
    }

    split = fetch_massive_splits(
        "NVDA",
        start=date(2024, 6, 1),
        end=date(2024, 6, 30),
        api_key="secret",
        get_fn=_fake_pages(split_payload),
    )[0]
    dividend = fetch_massive_dividends(
        "AAPL",
        start=date(2025, 2, 1),
        end=date(2025, 2, 28),
        api_key="secret",
        get_fn=_fake_pages(dividend_payload),
    )[0]

    assert (split.kind, split.effective_date, split.provider_id) == (
        "split",
        date(2024, 6, 10),
        "split-id",
    )
    assert split.split_from == Decimal("1")
    assert split.split_to == Decimal("10")
    assert (dividend.kind, dividend.effective_date, dividend.provider_id) == (
        "dividend",
        date(2025, 2, 10),
        "dividend-id",
    )
    assert dividend.cash_amount == Decimal("0.25")


def test_massive_open_close_parses_regular_and_extended_session_probe() -> None:
    payload = {
        "status": "OK",
        "symbol": "AAPL",
        "from": "2025-01-02",
        "open": Decimal("242.70"),
        "high": Decimal("244.18"),
        "low": Decimal("241.89"),
        "close": Decimal("243.85"),
        "volume": Decimal("40000000.5"),
        "preMarket": Decimal("242.10"),
        "afterHours": Decimal("244.00"),
    }

    result = fetch_massive_open_close(
        "AAPL",
        session_date=date(2025, 1, 2),
        api_key="secret",
        get_fn=_fake_pages(payload),
    )

    assert result.session_date == date(2025, 1, 2)
    assert result.volume == Decimal("40000000.5")
    assert result.pre_market == Decimal("242.10")
    assert result.after_hours == Decimal("244.00")


def test_minute_reconstruction_uses_exact_new_york_regular_session_and_decimal_math() -> None:
    payload = {
        "adjusted": True,
        "status": "OK",
        "queryCount": Decimal("5"),
        "resultsCount": Decimal("5"),
        "results": [
            {
                "o": Decimal("99"),
                "h": Decimal("100"),
                "l": Decimal("98"),
                "c": Decimal("99.5"),
                "v": Decimal("10.1"),
                "t": _millis("2025-01-02T14:29:00Z"),
            },
            {
                "o": Decimal("100.125"),
                "h": Decimal("101.250"),
                "l": Decimal("99.875"),
                "c": Decimal("101.000"),
                "v": Decimal("100.125"),
                "t": _millis("2025-01-02T14:30:00Z"),
            },
            {
                "o": Decimal("101.000"),
                "h": Decimal("102.500"),
                "l": Decimal("100.500"),
                "c": Decimal("102.000"),
                "v": Decimal("200.250"),
                "t": _millis("2025-01-02T14:31:00Z"),
            },
            {
                "o": Decimal("103.000"),
                "h": Decimal("104.000"),
                "l": Decimal("102.750"),
                "c": Decimal("103.500"),
                "v": Decimal("300.375"),
                "t": _millis("2025-01-02T20:59:00Z"),
            },
            {
                "o": Decimal("104"),
                "h": Decimal("105"),
                "l": Decimal("103"),
                "c": Decimal("104.5"),
                "v": Decimal("20.2"),
                "t": _millis("2025-01-02T21:00:00Z"),
            },
        ],
    }
    calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    def recording_get(url: str, params: dict[str, str], headers: dict[str, str]):
        calls.append((url, params, headers))
        return payload

    series = fetch_massive_minutes(
        "AAPL",
        session_date=date(2025, 1, 2),
        api_key="secret",
        get_fn=recording_get,
    )
    reconstructed = reconstruct_massive_session(series)

    assert calls[0][0].endswith("/v2/aggs/ticker/AAPL/range/1/minute/2025-01-02/2025-01-02")
    assert calls[0][1] == {"adjusted": "true", "sort": "asc", "limit": "50000"}
    assert calls[0][2] == {"Authorization": "Bearer secret"}
    assert reconstructed.regular is not None
    assert reconstructed.regular.open == Decimal("100.125")
    assert reconstructed.regular.high == Decimal("104.000")
    assert reconstructed.regular.low == Decimal("99.875")
    assert reconstructed.regular.close == Decimal("103.500")
    assert reconstructed.regular.volume == Decimal("600.750")
    assert reconstructed.regular.session_scope is SessionScope.REGULAR
    assert reconstructed.all_session is not None
    assert reconstructed.all_session.volume == Decimal("631.05")
    assert reconstructed.observed_regular_minutes == 3
    assert reconstructed.expected_regular_minutes == 390
    assert reconstructed.gap_reason(datetime(2025, 1, 2, 9, 32)) == "no_qualifying_trade"
    assert reconstructed.request.pagination_complete is True
    assert "secret" not in str(reconstructed.request.as_dict())


def test_minute_reconstruction_handles_dst_without_timestamp_reinterpretation() -> None:
    payload = {
        "adjusted": True,
        "status": "OK",
        "queryCount": Decimal("1"),
        "resultsCount": Decimal("1"),
        "results": [
            {
                "o": Decimal("1"),
                "h": Decimal("2"),
                "l": Decimal("1"),
                "c": Decimal("2"),
                "v": Decimal("3.25"),
                "t": _millis("2025-07-01T13:30:00Z"),
            },
        ],
    }

    series = fetch_massive_minutes(
        "AAPL",
        session_date=date(2025, 7, 1),
        api_key="secret",
        get_fn=_fake_pages(payload),
    )
    reconstructed = reconstruct_massive_session(series)

    assert series.bars[0].observed_at.isoformat() == "2025-07-01T09:30:00-04:00"
    assert reconstructed.regular is not None
    assert reconstructed.regular.volume == Decimal("3.25")


def test_minute_retrieval_marks_empty_provider_data_distinct_from_absent_trade_minutes() -> None:
    series = fetch_massive_minutes(
        "AAPL",
        session_date=date(2025, 1, 2),
        api_key="secret",
        get_fn=_fake_pages(
            {
                "adjusted": True,
                "status": "OK",
                "queryCount": Decimal("0"),
                "resultsCount": Decimal("0"),
                "results": [],
            }
        ),
    )

    reconstructed = reconstruct_massive_session(series)

    assert reconstructed.retrieval_status == "provider_data_unavailable"
    assert reconstructed.regular is None
    assert reconstructed.gaps == ()


def test_minute_retrieval_rejects_response_count_gap() -> None:
    payload = {
        "adjusted": True,
        "status": "OK",
        "queryCount": Decimal("2"),
        "resultsCount": Decimal("2"),
        "results": [
            {
                "o": Decimal("1"),
                "h": Decimal("2"),
                "l": Decimal("1"),
                "c": Decimal("2"),
                "v": Decimal("3"),
                "t": _millis("2025-01-02T14:30:00Z"),
            },
        ],
    }

    with pytest.raises(MassiveSemanticError, match="retrieval or pagination gap"):
        fetch_massive_minutes(
            "AAPL",
            session_date=date(2025, 1, 2),
            api_key="secret",
            get_fn=_fake_pages(payload),
        )


def test_minute_retrieval_rejects_timestamp_from_wrong_new_york_session() -> None:
    payload = {
        "adjusted": True,
        "status": "OK",
        "queryCount": Decimal("1"),
        "resultsCount": Decimal("1"),
        "results": [
            {
                "o": Decimal("1"),
                "h": Decimal("2"),
                "l": Decimal("1"),
                "c": Decimal("2"),
                "v": Decimal("3"),
                "t": _millis("2025-01-03T14:30:00Z"),
            },
        ],
    }

    with pytest.raises(MassiveSemanticError, match="requested New York session"):
        fetch_massive_minutes(
            "AAPL",
            session_date=date(2025, 1, 2),
            api_key="secret",
            get_fn=_fake_pages(payload),
        )
