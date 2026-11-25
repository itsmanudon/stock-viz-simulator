"""Production fail-closed checks on Settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from stockviz.settings import Settings

_PROD_TOKEN = "not-the-committed-dev-default"


def test_development_allows_committed_dev_defaults() -> None:
    settings = Settings(environment="development")
    assert settings.internal_api_token == "dev-internal-token-change-me"


def test_production_rejects_dev_internal_token() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_API_TOKEN"):
        Settings(
            environment="production",
            internal_api_token="dev-internal-token-change-me",
        )


def test_production_accepts_a_real_internal_token() -> None:
    settings = Settings(environment="production", internal_api_token=_PROD_TOKEN)
    assert settings.internal_api_token == _PROD_TOKEN


def test_production_does_not_require_unused_nextauth_jwt_secret() -> None:
    """The auth bridge signs with INTERNAL_API_TOKEN; the leftover secret
    must not block a correct deploy if it is still the committed default."""
    settings = Settings(environment="production", internal_api_token=_PROD_TOKEN)
    assert settings.nextauth_jwt_secret == "dev-secret-change-me"


def test_massive_shadow_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="MASSIVE_API_KEY"):
        Settings(massive_shadow_enabled=True, massive_api_key="")


def test_massive_shadow_accepts_key() -> None:
    settings = Settings(massive_shadow_enabled=True, massive_api_key="private-test-key")
    assert settings.massive_shadow_enabled is True


def test_massive_shadow_lookback_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="MASSIVE_SHADOW_LOOKBACK_DAYS"):
        Settings(massive_shadow_lookback_days=0)


def test_retired_news_and_sentiment_variables_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A0: the legacy pipeline's variables may still be set on a host; they
    must neither fail validation nor reach the settings object."""
    for name, value in {
        "NEWS_PROVIDER": "newsdata",
        "NEWSDATA_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "SENTIMENT_PROVIDER": "anthropic",
        "SENTIMENT_SERVICE_URL": "",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings()
    for field in ("news_provider", "newsdata_key", "anthropic_api_key", "sentiment_provider"):
        assert not hasattr(settings, field)
