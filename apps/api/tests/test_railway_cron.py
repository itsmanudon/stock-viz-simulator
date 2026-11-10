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
    # `news` is the one job with a tolerated exit code (2 = no provider key).
    assert set(jobs) - wrapped == {"news"}
    assert "stockviz.cli news || [ $? -eq 2 ] || rc=1" in steps


def test_cron_receives_the_internal_api_token() -> None:
    code = _code(_source())
    cron = re.search(r'service\("cron", \{(.*?)\n  \}\);', code, re.DOTALL)
    assert cron, "cron service block not found"
    # settings.py refuses to load in production with the dev default token,
    # and every CLI command imports settings.
    assert "INTERNAL_API_TOKEN" in cron.group(1)
