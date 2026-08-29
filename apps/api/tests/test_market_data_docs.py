from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_market_data_runbook_documents_canonical_and_shadow_contracts() -> None:
    text = (REPO_ROOT / "docs" / "MARKET_DATA.md").read_text(encoding="utf-8")

    required = (
        "yfinance remains the sole persisted/default provider",
        "split-adjusted",
        "not dividend-adjusted",
        "America/New_York",
        "provider_daily",
        "completed daily",
        "MASSIVE_SHADOW_ENABLED",
        "MASSIVE_API_KEY",
        "artifacts/private",
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "TSLA",
        "JPM",
        "technical provider gate",
        "commercial licensing gate",
        "do not cut over",
        "NUMERIC",
        "exchange-qualified",
        "historical FX",
    )
    for phrase in required:
        assert phrase.lower() in text.lower(), phrase


def test_public_docs_link_market_data_runbook_and_private_artifacts() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    setup = (REPO_ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
    limitations = (REPO_ROOT / "docs" / "KNOWN_LIMITATIONS.md").read_text(encoding="utf-8")

    assert "docs/MARKET_DATA.md" in readme
    assert "verify:pipeline:clean" in setup
    assert "verify:providers:live" in setup
    assert "artifacts/private" in setup
    assert "Massive" in limitations
    assert "Individual" in limitations
