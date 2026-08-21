"""Tests for the sentiment providers and their selection.

The old suite tested a single `score_headlines` function that returned bare
labels. These cover the same Anthropic behaviour through the provider
interface, plus the two things the pipeline gained: an HTTP provider (the seam
a separate sentiment repo plugs into) and explicit provider selection.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from stockviz.services.sentiment import NullProvider, get_provider
from stockviz.services.sentiment import anthropic_provider as anthropic_mod
from stockviz.services.sentiment.anthropic_provider import AnthropicProvider
from stockviz.services.sentiment.base import (
    SentimentInput,
    SentimentScore,
    label_from_score,
    score_from_label,
)
from stockviz.services.sentiment.http_provider import HttpProvider
from stockviz.settings import Settings


def _inputs(*headlines: str) -> list[SentimentInput]:
    return [SentimentInput(headline=h) for h in headlines]


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


def test_score_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        SentimentScore(label="positive", score=1.5, model="m")
    with pytest.raises(ValueError):
        SentimentScore(label="positive", score=0.5, model="m", confidence=1.5)
    with pytest.raises(ValueError):
        SentimentScore(label="sideways", score=0.5, model="m")  # type: ignore[arg-type]


def test_label_and_score_round_trip() -> None:
    assert label_from_score(0.9) == "positive"
    assert label_from_score(-0.9) == "negative"
    assert label_from_score(0.0) == "neutral"
    # Inside the neutral band, a weak signal is not a call either way.
    assert label_from_score(0.1) == "neutral"
    assert score_from_label("positive") == 1.0
    assert score_from_label("negative") == -1.0


def test_input_combines_headline_and_summary() -> None:
    """The old implementation discarded the summary; models do better with it."""
    item = SentimentInput(headline="Acme beats estimates", summary="Revenue up 12% YoY.")
    assert "Acme beats estimates" in item.as_text()
    assert "Revenue up 12% YoY." in item.as_text()
    assert SentimentInput(headline="Solo").as_text() == "Solo"


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]


class _FakeClient:
    def __init__(self, raise_on_call: bool = False) -> None:
        self.raise_on_call = raise_on_call
        self.calls: list[dict] = []
        self.messages = self  # so ``client.messages.create`` works

    def create(self, **kwargs) -> _FakeResponse:
        self.calls.append(kwargs)
        if self.raise_on_call:
            raise RuntimeError("simulated failure")
        return _FakeResponse('{"sentiments": ["positive", "neutral", "negative"]}')


def test_anthropic_returns_all_none_without_key() -> None:
    provider = AnthropicProvider(api_key="")
    assert provider.score(_inputs("X", "Y", "Z")) == [None, None, None]


def test_anthropic_returns_empty_for_empty_input() -> None:
    assert AnthropicProvider(api_key="anything").score([]) == []


def test_anthropic_happy_path() -> None:
    fake = _FakeClient()
    with patch.object(anthropic_mod, "Anthropic", return_value=fake, create=True):
        out = AnthropicProvider(api_key="ant-test").score(_inputs("a", "b", "c"))

    assert [s.label for s in out] == ["positive", "neutral", "negative"]  # type: ignore[union-attr]
    assert [s.score for s in out] == [1.0, 0.0, -1.0]  # type: ignore[union-attr]
    assert all(s.model.startswith("claude-haiku-4-5") for s in out)  # type: ignore[union-attr]
    assert len(fake.calls) == 1


def test_anthropic_batches() -> None:
    fake = _FakeClient()
    with patch.object(anthropic_mod, "Anthropic", return_value=fake, create=True):
        out = AnthropicProvider(api_key="ant-test", batch_size=2).score(_inputs("a", "b", "c"))
    assert len(out) == 3
    assert len(fake.calls) == 2


def test_anthropic_degrades_to_none_on_api_error() -> None:
    fake = _FakeClient(raise_on_call=True)
    with patch.object(anthropic_mod, "Anthropic", return_value=fake, create=True):
        out = AnthropicProvider(api_key="ant-test").score(_inputs("a", "b", "c"))
    assert out == [None, None, None]
    # Retried before giving up, rather than dropping the batch on one blip.
    assert len(fake.calls) == 3


def test_anthropic_degrades_to_none_on_malformed_response() -> None:
    class _BadClient(_FakeClient):
        def create(self, **kwargs) -> _FakeResponse:
            self.calls.append(kwargs)
            return _FakeResponse("not json at all")

    with patch.object(anthropic_mod, "Anthropic", return_value=_BadClient(), create=True):
        out = AnthropicProvider(api_key="ant-test").score(_inputs("a", "b"))
    assert out == [None, None]


def test_anthropic_degrades_to_none_on_wrong_length() -> None:
    class _ShortClient(_FakeClient):
        def create(self, **kwargs) -> _FakeResponse:
            self.calls.append(kwargs)
            return _FakeResponse('{"sentiments": ["positive"]}')  # too short for 3

    with patch.object(anthropic_mod, "Anthropic", return_value=_ShortClient(), create=True):
        out = AnthropicProvider(api_key="ant-test").score(_inputs("a", "b", "c"))
    assert out == [None, None, None]


# ---------------------------------------------------------------------------
# HTTP provider — the seam a separate sentiment service plugs into
# ---------------------------------------------------------------------------


def _http_provider(handler) -> HttpProvider:
    transport = httpx.MockTransport(handler)
    return HttpProvider(
        base_url="http://sentiment.internal",
        client=httpx.Client(transport=transport),
        model_hint="test-model",
    )


def test_http_parses_a_well_formed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/score"
        return httpx.Response(
            200,
            json={
                "model": "finbert-v2",
                "results": [
                    {"label": "positive", "score": 0.82, "confidence": 0.91},
                    {"label": "negative", "score": -0.4},
                ],
            },
        )

    out = _http_provider(handler).score(_inputs("a", "b"))
    assert out[0] is not None and out[0].label == "positive"
    assert out[0].score == pytest.approx(0.82)
    assert out[0].confidence == pytest.approx(0.91)
    assert out[0].model == "finbert-v2"
    assert out[1] is not None and out[1].confidence is None


def test_http_passes_a_bearer_token_when_configured() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"model": "m", "results": [{"score": 0.5}]})

    provider = HttpProvider(
        base_url="http://sentiment.internal",
        token="s3cret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.score(_inputs("a"))
    assert seen["auth"] == "Bearer s3cret"


def test_http_derives_a_label_when_the_service_omits_one() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "results": [{"score": -0.7}]})

    out = _http_provider(handler).score(_inputs("a"))
    assert out[0] is not None and out[0].label == "negative"


def test_http_preserves_nulls_for_unscorable_documents() -> None:
    """A null result means "retry later", not "neutral"."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"model": "m", "results": [{"score": 0.5}, None, {"score": 0.1}]}
        )

    out = _http_provider(handler).score(_inputs("a", "b", "c"))
    assert out[1] is None
    assert out[0] is not None and out[2] is not None


def test_http_rejects_a_length_mismatch() -> None:
    """A service that returns the wrong number of results would silently
    misalign scores against articles."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "results": [{"score": 0.5}]})

    out = _http_provider(handler).score(_inputs("a", "b", "c"))
    assert out == [None, None, None]


def test_http_clamps_out_of_range_scores() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"model": "m", "results": [{"score": 4.2}, {"score": -9.0}]}
        )

    out = _http_provider(handler).score(_inputs("a", "b"))
    assert out[0] is not None and out[0].score == 1.0
    assert out[1] is not None and out[1].score == -1.0


def test_http_degrades_to_none_on_server_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    out = _http_provider(handler).score(_inputs("a", "b"))
    assert out == [None, None]


def test_http_skips_when_no_url_configured() -> None:
    assert HttpProvider(base_url="").score(_inputs("a")) == [None]


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def test_default_is_null_provider() -> None:
    provider = get_provider(Settings(sentiment_provider="", anthropic_api_key=""))
    assert isinstance(provider, NullProvider)
    assert provider.score(_inputs("a", "b")) == [None, None]


def test_anthropic_key_alone_still_selects_anthropic() -> None:
    """Back-compat: a deployment that only set ANTHROPIC_API_KEY keeps working."""
    provider = get_provider(Settings(sentiment_provider="", anthropic_api_key="ant-test"))
    assert isinstance(provider, AnthropicProvider)


def test_http_provider_is_selectable() -> None:
    provider = get_provider(
        Settings(sentiment_provider="http", sentiment_service_url="http://svc.internal")
    )
    assert isinstance(provider, HttpProvider)


def test_selection_falls_back_to_null_when_misconfigured() -> None:
    # Named a provider but gave it nothing to talk to.
    assert isinstance(get_provider(Settings(sentiment_provider="http")), NullProvider)
    assert isinstance(get_provider(Settings(sentiment_provider="anthropic")), NullProvider)
    assert isinstance(get_provider(Settings(sentiment_provider="wat")), NullProvider)
