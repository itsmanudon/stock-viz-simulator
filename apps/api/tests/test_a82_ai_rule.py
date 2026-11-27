"""A8.2 / A8.3: the provider interface, Ollama's wire shape, and the rule translator.

A fake provider and a fake HTTP post stand in for the model; no test calls
Ollama or any provider.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

from stockviz.services.ai import rules as ai_rules
from stockviz.services.ai.provider import (
    AiNotConfigured,
    AiProviderError,
    Message,
    OllamaProvider,
    provider_from_settings,
)
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


class Fake:
    name = "fake"
    model = "fake-1"

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        self.calls.append(list(messages))
        return self.answers.pop(0)


def test_extract_rule_strips_fences_and_labels() -> None:
    assert ai_rules.extract_rule("```dsl\nclose > sma(close, 50)\n```") == "close > sma(close, 50)"
    assert ai_rules.extract_rule("Rule: rsi(14) < 30\nThis means ...") == "rsi(14) < 30"
    assert ai_rules.extract_rule("  ") == ""


def test_prompt_lists_the_live_registry() -> None:
    prompt = ai_rules.system_prompt()
    assert (
        "rsi(" in prompt and "supertrend(" in prompt and "Fundamental metrics: market_cap" in prompt
    )


def test_a_valid_first_draft_is_returned_checked() -> None:
    fake = Fake(["close > sma(close, 200) and rsi(14) < 30"])
    out = ai_rules.translate(fake, "above the 200-day average and oversold")
    assert out.check.valid and out.check.canonical and len(out.attempts) == 1
    assert fake.calls[0][0].role == "system" and fake.calls[0][1].content.startswith("above")


def test_a_failed_draft_gets_one_retry_with_the_error() -> None:
    fake = Fake(["close > smaa(close, 20)", "close > sma(close, 20)"])
    out = ai_rules.translate(fake, "above the 20-day average")
    assert [a.check.valid for a in out.attempts] == [False, True]
    assert "fails the check" in fake.calls[1][-1].content


def test_a_draft_that_still_fails_comes_back_with_its_error() -> None:
    fake = Fake(["close >>> 1", "volume crosses_above"])
    out = ai_rules.translate(fake, "nonsense")
    assert not out.check.valid and out.check.error is not None
    assert out.rule == "volume crosses_above" and len(out.attempts) == 2


def test_ollama_wire_shape_and_errors() -> None:
    seen: dict[str, Any] = {}

    def post(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
        seen.update(url=url, body=body)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "close > 1"}})

    p = OllamaProvider(model="gemma4:e4b", url="http://127.0.0.1:11434/", post=post)
    assert p.complete([Message("user", "hi")]) == "close > 1"
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["body"]["stream"] is False and seen["body"]["model"] == "gemma4:e4b"

    def down(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(AiProviderError, match="not reachable"):
        OllamaProvider(model="m", post=down).complete([Message("user", "x")])
    bad = OllamaProvider(model="m", post=lambda u, b, t: httpx.Response(500))
    with pytest.raises(AiProviderError, match="HTTP 500"):
        bad.complete([Message("user", "x")])


def test_off_without_a_model() -> None:
    class S:
        ollama_model = ""
        ollama_url = ""

    with pytest.raises(AiNotConfigured, match="OLLAMA_MODEL"):
        provider_from_settings(S())


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer " + jose_jwt.encode({"sub": "1"}, SECRET, algorithm="HS256")}


def test_routes(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "")
    get_settings.cache_clear()
    try:
        assert client.get("/v1/ai/status").json()["configured"] is False
        assert client.post("/v1/ai/rule", json={"text": "above the 50 day"}).status_code == 401
        off = client.post("/v1/ai/rule", json={"text": "above the 50 day"}, headers=_auth())
        assert off.status_code == 409 and "OLLAMA_MODEL" in off.json()["detail"]
        fake = Fake(["close > sma(close, 50)"])
        monkeypatch.setattr("stockviz.routers.ai.provider_from_settings", lambda s: fake)
        out = client.post("/v1/ai/rule", json={"text": "above the 50 day"}, headers=_auth()).json()
        assert out["check"]["valid"] and out["provider"] == "fake" and "checker" in out["note"]
    finally:
        get_settings.cache_clear()
