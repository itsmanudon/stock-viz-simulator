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
