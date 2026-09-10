"""Static safety contract for the isolated, credential-free Docker workflow."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DOCKERFILE = REPO_ROOT / "apps" / "api" / "Dockerfile"
API_DOCKERIGNORE = REPO_ROOT / "apps" / "api" / ".dockerignore"
VERIFY_COMPOSE = REPO_ROOT / "infra" / "docker-compose.verify.yml"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-pipeline-clean.ps1"
PACKAGE_JSON = REPO_ROOT / "package.json"


def test_api_test_target_uses_the_same_source_and_lockfile() -> None:
    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")
    dockerignore = API_DOCKERIGNORE.read_text(encoding="utf-8")

    assert "FROM builder AS test" in dockerfile
    assert "ENV PATH=/opt/venv/bin:$PATH" in dockerfile
    assert "uv sync --frozen" in dockerfile
    assert "COPY tests ./tests" in dockerfile
    assert 'CMD ["pytest"]' in dockerfile
    assert "\ntests\n" not in f"\n{dockerignore}"
    assert "FROM python:3.12-slim AS runtime" in dockerfile


def test_clean_verification_builds_api_and_web_from_source() -> None:
    compose = VERIFY_COMPOSE.read_text(encoding="utf-8")
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")

    assert "target: test" in compose
    assert "target: runtime" in compose
    assert "build --no-cache api web api-tests" in script
    assert "stockviz_pipeline_verify_postgres_data" in compose
    assert "MASSIVE_API_KEY" not in compose
    assert "NEWSDATA_KEY" not in compose
    assert "docker cp" not in script.lower()
    assert "docker commit" not in script.lower()


def test_clean_verification_is_isolated_and_always_torn_down() -> None:
    compose = VERIFY_COMPOSE.read_text(encoding="utf-8")
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")

    for value in ("15434", "19092", "18000", "13100"):
        assert value in compose
    assert "stockviz-pipeline-verify" in script
    assert "down --volumes --remove-orphans" in script
    assert "finally" in script
    assert "artifacts/verification" in script.replace("\\", "/")


def test_clean_verification_runs_market_news_and_kafka_paths() -> None:
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")

    for test in (
        "test_market_event_pipeline_roundtrip",
        "test_news_sentiment_event_pipeline_roundtrip",
        "tests/test_market_news_pipeline.py",
        "tests/test_outbox.py",
    ):
        assert test in script
    assert "http://127.0.0.1:18000/live" in script
    assert "http://127.0.0.1:13100/api/health" in script


def test_package_exposes_clean_verification_command() -> None:
    package = PACKAGE_JSON.read_text(encoding="utf-8")

    assert '"verify:pipeline:clean"' in package
    assert "verify-pipeline-clean.ps1" in package
