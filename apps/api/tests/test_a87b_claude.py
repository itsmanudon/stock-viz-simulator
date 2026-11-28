"""A8.7b (M11.2 BYOK): Claude keys through the official anthropic SDK (faked)."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlmodel import Session

from stockviz.services.ai import keys
from stockviz.services.ai.claude import (
    DEFAULT_MODEL,
    FALLBACK_BETA,
    FALLBACK_MODELS,
    ClaudeProvider,
)
from stockviz.services.ai.provider import AiProviderError, Message
from tests.test_drills import _user

SECRET = "sk-ant-test-0123456789ABCD"


class FakeMessages:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.reply = reply
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply


def _reply(text: str = "Answer [1].", stop: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
    )


def _provider(model: str, messages: FakeMessages, beta: FakeMessages | None = None):
    seen_keys: list[str] = []

    def factory(key: str):
        seen_keys.append(key)
        return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=beta or messages))

    return ClaudeProvider(model=model, api_key=SECRET, client_factory=factory), seen_keys


def test_request_shape_and_fallback() -> None:
    plain, beta = FakeMessages(_reply()), FakeMessages(_reply("Fallback on [2]."))
    p, seen = _provider("claude-opus-5-5", plain, beta)
    out = p.complete([Message("system", "Only the sources."), Message("user", "Q?")])
    assert out == "Fallback on [2]." and seen == [SECRET] and plain.calls == []
    call = beta.calls[0]
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["system"] == "Only the sources." and call["model"] == "claude-opus-5-5"
    assert call["messages"] == [{"role": "user", "content": "Q?"}]
    assert "temperature" not in call and call["max_tokens"] > 1000
    other = FakeMessages(_reply())
    p2, _ = _provider("claude-haiku-5-5", other)
    assert p2.complete([Message("user", "Q?")]) == "Answer [1]."
    assert "betas" not in other.calls[0] and "system" not in other.calls[0]
    assert SECRET not in repr(p)


def test_default_model_is_haiku() -> None:
    assert DEFAULT_MODEL == "claude-haiku-5-5" and DEFAULT_MODEL not in FALLBACK_MODELS


def _status_error(cls, status: int):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, json={"error": {"message": SECRET}})
    return cls(message=f"echo {SECRET}", response=response, body=None)


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (lambda: _status_error(anthropic.AuthenticationError, 401), "refused the key"),
        (lambda: _status_error(anthropic.PermissionDeniedError, 403), "refused the key"),
        (lambda: _status_error(anthropic.RateLimitError, 429), "rate limit"),
        (lambda: _status_error(anthropic.NotFoundError, 404), "does not know that model"),
        (lambda: _status_error(anthropic.InternalServerError, 500), "HTTP 500"),
        (
            lambda: anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")),
            "not reachable",
        ),
        (
            lambda: anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")),
            "timed out",
        ),
    ],
)
def test_errors_are_fixed_text(error, text) -> None:
    p, _ = _provider("claude-haiku-5-5", FakeMessages(error=error()))
    with pytest.raises(AiProviderError, match=text) as err:
        p.complete([Message("user", "Q?")])
    assert SECRET not in str(err.value)


def test_refusal_and_empty_answers() -> None:
    p, _ = _provider("claude-haiku-5-5", FakeMessages(_reply("", stop="refusal")))
    with pytest.raises(AiProviderError, match="declined"):
        p.complete([Message("user", "Q?")])
    q, _ = _provider("claude-haiku-5-5", FakeMessages(_reply("   ")))
    with pytest.raises(AiProviderError, match="no text"):
        q.complete([Message("user", "Q?")])


def test_saved_claude_key_becomes_a_claude_provider(session: Session) -> None:
    settings = SimpleNamespace(
        app_encryption_key=SecretStr(Fernet.generate_key().decode()), is_production=False
    )
    uid = _user(session, "c@stockviz.dev")
    saved = keys.save_key(session, settings, uid, "anthropic", api_key=SECRET, model="",
                          base_url=None)  # fmt: skip
    assert saved.model == DEFAULT_MODEL and saved.base_url is None and saved.key_last4 == "ABCD"
    p = keys.provider_for(session, settings, uid, "anthropic")
    assert isinstance(p, ClaudeProvider) and p.api_key == SECRET and p.name == "anthropic"
