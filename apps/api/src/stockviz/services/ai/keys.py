"""Save, list and use users' own AI keys (A8.7, M11.2 BYOK).

Keys are encrypted with Fernet under ``APP_ENCRYPTION_KEY`` (owner, 27 Nov
2026: generated locally, never committed). Without it saving is refused and
saved keys cannot be used. A key is returned to nobody: reads give the
provider, model, base URL and the last four characters only. Changing the
server key makes every saved key unreadable; the user is told to save it again.

Providers: ``openai_compatible`` (any endpoint speaking the OpenAI
chat-completions shape: OpenAI, OpenRouter, Groq, a local LM Studio) and,
since A8.7b, ``anthropic`` (Claude through the official ``anthropic`` SDK;
owner, 27 Nov 2026; no base URL: the SDK's own endpoint).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import UserAiKey
from stockviz.services.ai.claude import DEFAULT_MODEL, ClaudeProvider
from stockviz.services.ai.openai_compat import OpenAICompatibleProvider, check_base_url
from stockviz.services.ai.provider import LLMProvider, provider_from_settings

USABLE_PROVIDERS = ("openai_compatible", "anthropic")
HELD: dict[str, str] = {}


class KeysOff(RuntimeError):
    """409: the server has no APP_ENCRYPTION_KEY."""


class KeyError_(ValueError):
    """422: the key, model or URL is not acceptable."""


class KeyMissing(LookupError):
    """404: no saved key for that provider."""


@dataclass(frozen=True)
class SavedKey:
    provider: str
    model: str
    base_url: str | None
    key_last4: str
    updated_at: Any


def _box(settings: Any) -> Fernet:
    raw = settings.app_encryption_key.get_secret_value().strip()
    if not raw:
        raise KeysOff("saved AI keys are off on this server: APP_ENCRYPTION_KEY is not set")
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise KeysOff("APP_ENCRYPTION_KEY is not a valid Fernet key") from exc


def keys_available(settings: Any) -> bool:
    try:
        _box(settings)
    except KeysOff:
        return False
    return True


def _row(session: Session, user_id: int, provider: str) -> UserAiKey | None:
    return session.exec(
        select(UserAiKey).where(
            col(UserAiKey.user_id) == user_id, col(UserAiKey.provider) == provider
        )
    ).first()


def _check_provider(provider: str) -> None:
    if provider in HELD:
        raise KeyError_(HELD[provider])
    if provider not in USABLE_PROVIDERS:
        raise KeyError_(f"provider must be one of {USABLE_PROVIDERS}")


def save_key(
    session: Session,
    settings: Any,
    user_id: int,
    provider: str,
    *,
    api_key: str,
    model: str,
    base_url: str | None,
) -> SavedKey:
    _check_provider(provider)
    box = _box(settings)
    key = api_key.strip()
    if len(key) < 8 or any(c.isspace() for c in key):
        raise KeyError_("the key looks incomplete")
    name = model.strip() or (DEFAULT_MODEL if provider == "anthropic" else "")
    if not name:
        raise KeyError_("name the model to use")
    if provider == "anthropic":
        if base_url:
            raise KeyError_("Claude keys use Anthropic's own endpoint; leave the base URL empty")
        if not name.startswith("claude-"):
            raise KeyError_("name a Claude model, e.g. claude-haiku-5-5")
        url = None
    else:
        url = check_base_url(base_url or "", local_allowed=not settings.is_production)
    row = _row(session, user_id, provider) or UserAiKey(
        user_id=user_id, provider=provider, ciphertext="", key_last4="", model=name
    )
    row.ciphertext = box.encrypt(key.encode()).decode()
    row.key_last4 = key[-4:]
    row.model = name[:100]
    row.base_url = url
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _saved(row)


def _saved(row: UserAiKey) -> SavedKey:
    return SavedKey(row.provider, row.model, row.base_url, row.key_last4, row.updated_at)


def list_keys(session: Session, user_id: int) -> list[SavedKey]:
    rows = session.exec(
        select(UserAiKey).where(col(UserAiKey.user_id) == user_id).order_by(col(UserAiKey.provider))
    ).all()
    return [_saved(r) for r in rows]


def delete_key(session: Session, user_id: int, provider: str) -> None:
    row = _row(session, user_id, provider)
    if row is None:
        raise KeyMissing("no saved key for that provider")
    session.delete(row)
    session.commit()


def provider_for(session: Session, settings: Any, user_id: int, choice: str) -> LLMProvider:
    """The provider a request asked for: the server's model, or the user's key."""
    if choice == "server":
        return provider_from_settings(settings)
    _check_provider(choice)
    row = _row(session, user_id, choice)
    if row is None:
        raise KeyMissing("you have no saved key for that provider")
    try:
        secret = _box(settings).decrypt(row.ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise KeysOff(
            "your saved key can no longer be read (the server key changed); save it again"
        ) from exc
    if choice == "anthropic":
        return ClaudeProvider(model=row.model, api_key=secret)
    return OpenAICompatibleProvider(model=row.model, base_url=row.base_url or "", api_key=secret)
