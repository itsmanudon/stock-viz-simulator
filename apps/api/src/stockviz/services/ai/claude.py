"""Claude through the official ``anthropic`` SDK, for users' own keys (A8.7b,
M11.2 BYOK). Owner, 27 Nov 2026: add the SDK; no paid call without the
owner's OK (every test fakes the client).

- ``messages.create`` with the user's model (default ``DEFAULT_MODEL``), the
  system prompt apart from the messages, and ``MAX_TOKENS``. No sampling
  parameters: current models reject them (and SDK 2.x has none).
- For models that support it, the server-side refusal fallback is on
  (``client.beta.messages.create`` with ``betas=[FALLBACK_BETA]`` and
  ``fallbacks="default"``): a declined request is re-run on a fallback model
  inside the same call. A response that still ends with
  ``stop_reason == "refusal"`` raises with a fixed message.
- The answer is the text blocks joined; thinking blocks are ignored.
- Errors are fixed text by class (key refused, rate limit, unreachable,
  HTTP status); never the key or Anthropic's message body.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from stockviz.services.ai.provider import AiProviderError, Message

DEFAULT_MODEL = "claude-haiku-5-5"  # owner, 28 Nov 2026: Haiku is the paid default
MAX_TOKENS = 16_000
TIMEOUT_SECONDS = 120.0
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset(
    {
        "claude-fable-5-2",
        "claude-fable-5-1",
        "claude-opus-5-5",
        "claude-opus-5",
        "claude-sonnet-5-5",
    }
)

ClientFactory = Callable[[str], Any]


def _client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=2)


@dataclass
class ClaudeProvider:
    model: str
    api_key: str
    client_factory: ClientFactory = _client
    name: str = "anthropic"

    def __repr__(self) -> str:  # never print the key
        return f"ClaudeProvider(model={self.model!r})"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> str:
        del temperature  # not sent: current Claude models take no sampling parameters
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        client = self.client_factory(self.api_key)
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": MAX_TOKENS, "messages": convo}
        if system:
            kwargs["system"] = system
        try:
            if self.model in FALLBACK_MODELS:
                response = client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs
                )
            else:
                response = client.messages.create(**kwargs)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise AiProviderError("Claude refused the key") from exc
        except anthropic.RateLimitError as exc:
            raise AiProviderError("Claude's rate limit was reached") from exc
        except anthropic.NotFoundError as exc:
            raise AiProviderError("Claude does not know that model") from exc
        except anthropic.APITimeoutError as exc:
            raise AiProviderError("Claude timed out") from exc
        except anthropic.APIConnectionError as exc:
            raise AiProviderError("Claude is not reachable") from exc
        except anthropic.APIStatusError as exc:
            raise AiProviderError(f"Claude answered HTTP {exc.status_code}") from exc
        if getattr(response, "stop_reason", None) == "refusal":
            raise AiProviderError("Claude declined this request")
        text = "".join(
            getattr(b, "text", "")
            for b in getattr(response, "content", [])
            if getattr(b, "type", "") == "text"
        ).strip()
        if not text:
            raise AiProviderError("Claude's answer had no text")
        return text
