"""The model provider interface (A8.3, M11.2 foundation).

The owner's 27 Nov 2026 answer: Ollama first (local, free, nothing leaves the
machine), then the user's own keys for Anthropic and OpenAI-compatible
endpoints (each paid test call needs the owner's approval; key storage waits
for ``APP_ENCRYPTION_KEY``). Only Ollama is built here.

``LLMProvider.complete(messages)`` returns the model's text; nothing else in
StockViz trusts it. Callers check what it drafts (a rule goes through
``/v1/rules/check``) before anything runs.

Ollama is off until ``OLLAMA_MODEL`` is set (``OLLAMA_URL`` defaults to the
local daemon); a production host without a model has every AI control off.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

Role = Literal["system", "user", "assistant"]
Post = Callable[[str, dict[str, Any], float], httpx.Response]


class AiNotConfigured(RuntimeError):
    """No provider is set up on this server; ``str()`` says how to turn one on."""


class AiProviderError(RuntimeError):
    """The provider failed; the message is fixed (never the prompt or a key)."""


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str: ...


def default_post(url: str, body: dict[str, Any], timeout: float) -> httpx.Response:
    return httpx.post(url, json=body, timeout=timeout)


@dataclass
class OllamaProvider:
    """``POST {url}/api/chat`` with ``stream: false``; the answer is ``message.content``."""

    model: str
    url: str = "http://127.0.0.1:11434"
    timeout: float = 120.0
    post: Post = default_post
    name: str = "ollama"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            response = self.post(f"{self.url.rstrip('/')}/api/chat", body, self.timeout)
        except httpx.HTTPError as exc:
            raise AiProviderError(f"Ollama is not reachable ({exc.__class__.__name__})") from exc
        if response.status_code != 200:
            raise AiProviderError(f"Ollama answered HTTP {response.status_code}")
        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AiProviderError("Ollama's answer was not in the documented shape") from exc
        if not isinstance(content, str):
            raise AiProviderError("Ollama's answer was not text")
        return content


def provider_from_settings(settings: Any) -> LLMProvider:
    model = (getattr(settings, "ollama_model", "") or "").strip()
    if not model:
        raise AiNotConfigured(
            "AI is off on this server: set OLLAMA_MODEL (and OLLAMA_URL if Ollama is not local)."
        )
    return OllamaProvider(
        model=model, url=getattr(settings, "ollama_url", "") or OllamaProvider.url
    )
