"""The export's manifest and ``lab verify``.

The manifest is written by the API's ``stockviz.cli export-parquet``
(``apps/api/src/stockviz/services/export/parquet.py``). This package never
imports the API: the manifest and the directory layout are the contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

MANIFEST_NAME = "manifest.json"
SUPPORTED_SCHEMA_VERSIONS = (1,)


class ManifestError(RuntimeError):
    pass


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    if not path.exists():
        raise ManifestError(f"no {MANIFEST_NAME} in {root}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    version = manifest.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ManifestError(
            f"manifest schema version {version!r} is not supported "
            f"(this lab reads {', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))})"
        )
    return manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class VerifyReport:
    partitions: int = 0
    rows: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify(root: Path) -> VerifyReport:
    """Check every listed partition's hash and row count, and look for unlisted files."""
    manifest = load_manifest(root)
    report = VerifyReport()
    listed: set[Path] = set()
    for name, table in manifest["tables"].items():
        total = 0
        for part in table["partitions"]:
            report.partitions += 1
            path = root / part["path"]
            listed.add(path.resolve())
            if not path.exists():
                report.problems.append(f"{part['path']}: missing")
                continue
            digest = sha256_file(path)
            if digest != part["sha256"]:
                report.problems.append(
                    f"{part['path']}: sha256 {digest[:12]} != manifest {part['sha256'][:12]}"
                )
                continue
            rows = pq.ParquetFile(path).metadata.num_rows
            if rows != part["rows"]:
                report.problems.append(f"{part['path']}: {rows} rows != manifest {part['rows']}")
                continue
            total += rows
            report.rows += rows
        if total != table["rows"] and not any(p.startswith(f"{name}/") for p in report.problems):
            report.problems.append(f"{name}: {total} rows != manifest total {table['rows']}")
        unlisted = sorted(p for p in (root / name).rglob("*.parquet") if p.resolve() not in listed)
        report.problems += [f"{p.relative_to(root)}: not in the manifest" for p in unlisted]
    return report
