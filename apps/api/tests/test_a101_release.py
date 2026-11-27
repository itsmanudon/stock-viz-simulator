"""A10.1: the self-hosting release ships no market data, requires every secret,
binds to localhost, and `doctor` names problems without printing a secret."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services import doctor
from stockviz.settings import Settings
from tests.symbols import seed_symbols

REPO = Path(__file__).resolve().parents[3]
COMPOSE = REPO / "infra" / "compose.release.yml"
DOCKERFILE = REPO / "apps" / "api" / "Dockerfile"
SECRETS = ("POSTGRES_PASSWORD", "INTERNAL_API_TOKEN", "AUTH_SECRET")


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text())


def test_release_api_builds_the_release_target_without_seed_bars() -> None:
    api = _compose()["services"]["api"]
    assert api["build"]["target"] == "release"
    stages = re.split(r"^FROM ", DOCKERFILE.read_text(), flags=re.M)
    release = next(s for s in stages if s.startswith("python:3.12-slim AS release"))
    assert "stock-data-csv-files" not in release
    assert "companies.json" in release
    # The default target is still `runtime` (last), and it adds the seed bars.
    assert stages[-1].startswith("release AS runtime")
    assert "stock-data-csv-files" in stages[-1]


def test_no_service_mounts_data_or_seed_files() -> None:
    for name, svc in _compose()["services"].items():
        for vol in svc.get("volumes", []):
            assert not str(vol).startswith(("./", "../", "/")), (name, vol)
            assert "seed" not in str(vol) and "data/" not in str(vol), (name, vol)


def test_every_secret_is_required_and_no_secret_is_written_in() -> None:
    text = COMPOSE.read_text()
    for name in SECRETS:
        uses = re.findall(r"\$\{" + name + r"([^}]*)\}", text)
        assert uses and all(u.startswith(":?") for u in uses), name
    assert "stockviz_dev" not in text and "change-me" not in text


def test_ports_bind_to_localhost_only_and_no_dev_extras() -> None:
    services = _compose()["services"]
    assert set(services) == {"postgres", "api", "setup", "web"}
    for svc in services.values():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), port
    assert services["setup"]["command"][-1] == "seed"
    assert services["setup"]["profiles"] == ["setup"]


def test_env_template_lists_the_secrets_blank_and_is_ignored() -> None:
    lines = (REPO / "infra" / "release.env.example").read_text().splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    for name in SECRETS:
        assert values[name] == ""
    assert "infra/release.env" in (REPO / ".gitignore").read_text().splitlines()


def _settings(**kw: object) -> Settings:
    return Settings.model_validate({"internal_api_token": "x" * 40, **kw})


def test_secret_check() -> None:
    assert doctor.secret_checks(_settings())[0].status == "ok"
    dev = doctor.secret_checks(_settings(internal_api_token="dev-internal-token-change-me"))
    assert dev[0].status == "fail" and "default" in dev[0].detail
    assert doctor.secret_checks(_settings(internal_api_token="short"))[0].status == "fail"


def test_keys_are_named_never_printed() -> None:
    secret = "sk-very-secret-value-123"
    checks = doctor.key_checks(_settings(tiingo_api_key=secret, alpha_vantage_key=secret))
    by = {c.name: c for c in checks}
    assert by["TIINGO_API_KEY"].status == "ok" and by["FINNHUB_API_KEY"].status == "off"
    rendered = doctor.render(checks + doctor.secret_checks(_settings()))
    assert secret not in rendered and "x" * 40 not in rendered


def test_database_checks_and_exit(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor, "migration_check", lambda s: doctor.Check("migrations", "ok", "at head")
    )
    empty = {c.name: c for c in doctor.database_checks(session)}
    assert empty["symbols"].status == "warn" and empty["daily bars"].status == "warn"
    assert "no market data ships" in empty["daily bars"].detail
    seed_symbols(session, "ACME", currency="USD")
    session.add(PriceBar(ticker="ACME", ts=datetime(2026, 11, 20), interval="1d",
                         open=Decimal(1), high=Decimal(1), low=Decimal(1), close=Decimal(1),
                         volume=1, source="test"))  # fmt: skip
    session.commit()
    full = {c.name: c for c in doctor.database_checks(session)}
    assert full["daily bars"].detail == "1 stored, newest 2026-11-20"
    checks = doctor.run(session, _settings())
    assert not [c for c in checks if c.status == "fail"]
    bad = doctor.run(session, _settings(internal_api_token=""))
    assert [c.name for c in bad if c.status == "fail"] == ["INTERNAL_API_TOKEN"]
