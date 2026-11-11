"""Guards on the hosted nightly cron declared in ``.railway/railway.ts``.

The cron once ended every step in ``|| true``. Railway then reported SUCCESS
on nights when settings validation killed every step, so nobody saw that no
price refresh had run. These checks read the file as text: they keep the two
properties that would have exposed it.
"""

from __future__ import annotations

import re
from pathlib import Path

RAILWAY_TS = Path(__file__).resolve().parents[3] / ".railway" / "railway.ts"


def _source() -> str:
    return RAILWAY_TS.read_text(encoding="utf-8")


def _code(source: str) -> str:
    """Drop ``//`` and ``*`` comment lines so prose cannot satisfy a check."""
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )


def _eod_refresh(source: str) -> str:
    match = re.search(r"const EOD_REFRESH = \[(.*?)\]\.join\(", source, re.DOTALL)
    assert match, "EOD_REFRESH array not found in .railway/railway.ts"
    return match.group(1)


def test_cron_steps_do_not_mask_failures() -> None:
    steps = _eod_refresh(_code(_source()))
    assert "|| true" not in steps
    assert '"exit $rc"' in steps
    assert '"alembic upgrade head || exit 1"' in steps


def test_every_cli_job_records_its_failure() -> None:
    steps = _eod_refresh(_code(_source()))
    jobs = re.findall(r"python -m stockviz\.cli ([a-z-]+)", steps)
    assert len(jobs) >= 10
    wrapped = set(re.findall(r'job\("python -m stockviz\.cli ([a-z-]+)', steps))
    # Two jobs tolerate exit code 2: `news` (no provider key) and
    # `aegis-sync` (Aegis not configured yet).
    assert set(jobs) - wrapped == {"news", "aegis-sync"}
    assert "stockviz.cli news || [ $? -eq 2 ] || rc=1" in steps
    assert "stockviz.cli aegis-sync || [ $? -eq 2 ] || rc=1" in steps


def test_aegis_sync_runs_after_the_price_refresh_with_its_settings() -> None:
    code = _code(_source())
    steps = _eod_refresh(code)
    assert steps.index("stockviz.cli ingest") < steps.index("stockviz.cli aegis-sync")
    cron = re.search(r'service\("cron", \{(.*?)\n  \}\);', code, re.DOTALL)
    assert cron, "cron service block not found"
    for name in ("AEGIS_BASE_URL", "AEGIS_SIGNING_KEY", "AEGIS_ISSUER", "AEGIS_AUDIENCE"):
        # preserve(): set out of band, never in source, kept across re-applies.
        assert f"{name}: preserve()" in cron.group(1)


def test_cron_receives_the_internal_api_token() -> None:
    code = _code(_source())
    cron = re.search(r'service\("cron", \{(.*?)\n  \}\);', code, re.DOTALL)
    assert cron, "cron service block not found"
    # settings.py refuses to load in production with the dev default token,
    # and every CLI command imports settings.
    assert "INTERNAL_API_TOKEN" in cron.group(1)
