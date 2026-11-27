"""An OpenAI-compatible chat-completions provider for users' own keys (A8.7).

``POST {base_url}/chat/completions`` with ``Authorization: Bearer <key>`` and
``{"model", "messages", "temperature"}``; the answer is
``choices[0].message.content``. Works with any endpoint speaking that shape.

The base URL is the user's, so it goes through the webhook SSRF rules
(A2.3, ``delivery.channels``): https only (http for localhost outside
production), no credentials in it, every resolved address public, and the
request sent to the checked address with the host in ``Host`` and SNI, never
following a redirect. Errors are fixed text: never the key, the URL's query or
the provider's body.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from stockviz.services.ai.provider import AiProviderError, Message
from stockviz.services.delivery.channels import DeliveryError, check_url_syntax, pinned_target

TIMEOUT_SECONDS = 120.0
Send = Callable[[str, dict[str, str], dict[str, Any], dict[str, Any]], httpx.Response]


def _send(
    target: str, headers: dict[str, str], body: dict[str, Any], extensions: dict[str, Any]
) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        return client.post(target, json=body, headers=headers, extensions=extensions)


def check_base_url(url: str, *, local_allowed: bool) -> str:
    """The saved form of a base URL (no trailing slash); raises KeyError_-like ValueError."""
    from stockviz.services.ai.keys import KeyError_

    raw = url.strip().rstrip("/")
    if not raw:
        raise KeyError_("give the endpoint's base URL, e.g. https://api.openai.com/v1")
    parts = urlsplit(raw)
    if parts.query or parts.fragment:
        raise KeyError_("the base URL must not have a query or fragment")
    try:
        check_url_syntax(raw)
    except DeliveryError as exc:
        raise KeyError_(exc.message.replace("webhook", "endpoint")) from exc
    host = (parts.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") and not local_allowed:
        raise KeyError_("a local endpoint is allowed only in development")
    return raw


@dataclass
class OpenAICompatibleProvider:
    model: str
    base_url: str
    api_key: str
    send: Send = _send
    name: str = "openai_compatible"

    def __repr__(self) -> str:  # never print the key
        return f"OpenAICompatibleProvider(model={self.model!r}, base_url={self.base_url!r})"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        try:
            target, host = pinned_target(url)
        except DeliveryError as exc:
            raise AiProviderError(exc.message.replace("webhook", "endpoint")) from exc
        port = urlsplit(url).port
        headers = {
            "Host": host if port is None else f"{host}:{port}",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        extensions = {"sni_hostname": host} if url.startswith("https") else {}
        body = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        try:
            response = self.send(target, headers, body, extensions)
        except httpx.TimeoutException as exc:
            raise AiProviderError("the endpoint timed out") from exc
        except httpx.HTTPError as exc:
            raise AiProviderError(f"the endpoint is not reachable ({type(exc).__name__})") from exc
        if 300 <= response.status_code < 400:
            raise AiProviderError("the endpoint redirected; redirects are not followed")
        if response.status_code in (401, 403):
            raise AiProviderError("the endpoint refused the key")
        if response.status_code == 429:
            raise AiProviderError("the endpoint's rate limit was reached")
        if response.status_code != 200:
            raise AiProviderError(f"the endpoint answered HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AiProviderError(
                "the endpoint's answer was not in the chat-completions shape"
            ) from exc
        if not isinstance(content, str):
            raise AiProviderError("the endpoint's answer was not text")
        return content
