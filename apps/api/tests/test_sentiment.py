"""Tests for the headline sentiment classifier."""

from __future__ import annotations

from unittest.mock import patch

from stockviz.services import sentiment as sentiment_mod
from stockviz.services.sentiment import score_headlines


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
        # The schema constrains the response, but in tests we synthesize the
        # text payload directly. Mirror the prompt order: 3 alternating labels.
        return _FakeResponse('{"sentiments": ["positive", "neutral", "negative"]}')


def test_score_headlines_returns_all_none_without_key() -> None:
    headlines = ["X", "Y", "Z"]
    assert score_headlines(headlines, api_key="") == [None, None, None]


def test_score_headlines_returns_empty_for_empty_input() -> None:
    assert score_headlines([], api_key="anything") == []


def test_score_headlines_happy_path_with_mocked_client() -> None:
    fake = _FakeClient()
    with patch.object(sentiment_mod, "Anthropic", return_value=fake, create=True):
        out = score_headlines(["a", "b", "c"], api_key="ant-test")
    assert out == ["positive", "neutral", "negative"]
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"].startswith("claude-haiku-4-5")


def test_score_headlines_batches() -> None:
    fake = _FakeClient()
    with patch.object(sentiment_mod, "Anthropic", return_value=fake, create=True):
        # Batch size 2 → 2 calls for 3 headlines.
        out = score_headlines(["a", "b", "c"], api_key="ant-test", batch_size=2)
    assert len(out) == 3
    assert len(fake.calls) == 2


def test_score_headlines_returns_none_on_api_error() -> None:
    fake = _FakeClient(raise_on_call=True)
    with patch.object(sentiment_mod, "Anthropic", return_value=fake, create=True):
        out = score_headlines(["a", "b", "c"], api_key="ant-test")
    assert out == [None, None, None]


def test_score_headlines_returns_none_on_malformed_response() -> None:
    class _BadClient(_FakeClient):
        def create(self, **kwargs) -> _FakeResponse:
            self.calls.append(kwargs)
            return _FakeResponse("not json at all")

    fake = _BadClient()
    with patch.object(sentiment_mod, "Anthropic", return_value=fake, create=True):
        out = score_headlines(["a", "b"], api_key="ant-test")
    assert out == [None, None]


def test_score_headlines_returns_none_on_wrong_length() -> None:
    class _ShortClient(_FakeClient):
        def create(self, **kwargs) -> _FakeResponse:
            return _FakeResponse('{"sentiments": ["positive"]}')  # too short for 3 inputs

    with patch.object(sentiment_mod, "Anthropic", return_value=_ShortClient(), create=True):
        out = score_headlines(["a", "b", "c"], api_key="ant-test")
    assert out == [None, None, None]
