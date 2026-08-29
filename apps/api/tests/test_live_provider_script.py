"""Static safety contract for optional private live-provider verification."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "verify-providers-live.ps1"
PACKAGE_JSON = REPO_ROOT / "package.json"


def test_live_script_validates_explicit_selections_before_docker() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    first_docker_call = script.index("& docker")
    for marker in (
        "MASSIVE_SHADOW_ENABLED",
        "MASSIVE_API_KEY",
        "NEWS_PROVIDER",
        "NEWSDATA_KEY",
        "SENTIMENT_PROVIDER",
        "ANTHROPIC_API_KEY",
        "SENTIMENT_SERVICE_URL",
    ):
        assert marker in script[:first_docker_call]
    assert "MASSIVE_SHADOW_ENABLED=true is required" in script
    assert "NEWS_PROVIDER=newsdata requires NEWSDATA_KEY" in script


def test_live_script_never_embeds_or_prints_credential_values() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "Write-Host $env:MASSIVE_API_KEY" not in script
    assert "Write-Host $env:NEWSDATA_KEY" not in script
    assert '"MASSIVE_API_KEY=$' not in script
    assert '"NEWSDATA_KEY=$' not in script
    assert "-e MASSIVE_API_KEY" in script
    assert "-e NEWSDATA_KEY" in script


def test_live_script_uses_rebuilt_api_image_and_private_mount_only() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "stockviz-api:pipeline-verify" in script
    assert "build api" in script
    assert "/private-artifacts" in script
    assert "artifacts/private/live-verification" in script.replace("\\", "/")
    assert "docker cp" not in script.lower()
    assert " up -d api" not in script
    assert " up -d web" not in script


def test_live_script_invokes_primary_news_and_shadow_commands() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    for command in (
        "python -m stockviz.cli ingest",
        "python -m stockviz.cli news",
        "python -m stockviz.cli market-shadow",
    ):
        assert command in script
    for ticker in ("AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "JPM"):
        assert ticker in script


def test_package_exposes_optional_live_verification() -> None:
    package = PACKAGE_JSON.read_text(encoding="utf-8")

    assert '"verify:providers:live"' in package
    assert "verify-providers-live.ps1" in package
