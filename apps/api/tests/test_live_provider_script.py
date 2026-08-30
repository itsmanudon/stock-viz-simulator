"""Static safety contract for optional private live-provider verification."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_live_script_can_read_an_explicit_local_env_file_without_copying_it() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "param(" in script
    assert "$EnvFile" in script
    assert "Resolve-Path -LiteralPath $EnvFile" in script
    assert "Copy-Item" not in script


def test_package_exposes_optional_live_verification() -> None:
    package = PACKAGE_JSON.read_text(encoding="utf-8")

    assert '"verify:providers:live"' in package
    assert "verify-providers-live.ps1" in package


def test_massive_semantic_only_mode_skips_persistence_and_news(tmp_path: Path) -> None:
    powershell = shutil.which("powershell")
    if powershell is None or os.name != "nt":
        pytest.skip("PowerShell command interception is Windows-specific")

    env_file = tmp_path / ".env"
    env_file.write_text(
        "MASSIVE_SHADOW_ENABLED=true\nMASSIVE_API_KEY=test-only-key\n",
        encoding="utf-8",
    )
    docker_log = tmp_path / "docker.log"
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text(
        "@echo off\n"
        'echo %*>>"%FAKE_DOCKER_LOG%"\n'
        'if "%1"=="image" if "%2"=="inspect" echo sha256:test-image\n'
        "exit /b 0\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["FAKE_DOCKER_LOG"] = str(docker_log)
    environment["PATH"] = f"{tmp_path}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-EnvFile",
            str(env_file),
            "-MassiveSemanticOnly",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    calls = docker_log.read_text(encoding="utf-8")
    assert "build api" in calls
    assert "python -m stockviz.cli market-shadow" in calls
    for forbidden in (
        "up -d --wait postgres",
        "alembic upgrade head",
        "python -m stockviz.cli seed",
        "python -m stockviz.cli ingest",
        "python -m stockviz.cli news",
    ):
        assert forbidden not in calls
