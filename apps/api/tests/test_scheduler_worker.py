"""The dedicated scheduler process is importable as a worker entrypoint."""

from __future__ import annotations

from stockviz.workers.scheduler import main as scheduler_main


def test_scheduler_worker_exposes_main() -> None:
    assert callable(scheduler_main)
