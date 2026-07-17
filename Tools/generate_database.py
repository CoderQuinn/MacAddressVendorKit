#!/usr/bin/env python3
"""Generate the offline IEEE MAC address vendor SQLite database."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "Sources/MacAddressVendorKit/Data/mac_address_vendors.sqlite3"
DEFAULT_MANIFEST = ROOT / "Sources/MacAddressVendorKit/Data/upstream_sources.json"
LANDING_PAGE = "https://standards.ieee.org/products-programs/regauth/"
SOURCES = {
    "MA-L": ("oui.csv", "https://standards-oui.ieee.org/oui/oui.csv", 24),
    "MA-M": ("mam.csv", "https://standards-oui.ieee.org/oui28/mam.csv", 28),
    "MA-S": ("oui36.csv", "https://standards-oui.ieee.org/oui36/oui36.csv", 36),
    "IAB": ("iab.csv", "https://standards-oui.ieee.org/iab/iab.csv", 36),
}


@dataclass(frozen=True, order=True)
class Assignment:
    prefix: str
    prefix_bits: int
    registry: str
    organization: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--snapshot-date")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MacAddressVendorKit-Updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def load_source_bytes(input_dir: Path | None) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for registry, (filename, url, _) in SOURCES.items():
        result[registry] = (
            (input_dir / filename).read_bytes()
            if input_dir is not None
            else download(url)
        )
    return result


def normalized_prefix(raw: str, prefix_bits: int) -> str:
    prefix = "".join(character for character in raw.upper() if character in "0123456789ABCDEF")
    expected_length = prefix_bits // 4
    if len(prefix) != expected_length:
        raise ValueError(
            f"invalid {prefix_bits}-bit assignment {raw!r}: expected {expected_length} hex digits"
        )
    return prefix


def parse_csv(data: bytes, expected_registry: str, prefix_bits: int) -> list[Assignment]:
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    required = {"Registry", "Assignment", "Organization Name"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError(f"{expected_registry}: unexpected CSV columns {reader.fieldnames}")
    assignments: list[Assignment] = []
    for row in reader:
        registry = (row.get("Registry") or "").strip()
        if registry != expected_registry:
            raise ValueError(f"expected registry {expected_registry}, got {registry}")
        organization = " ".join((row.get("Organization Name") or "").split())
        if not organization:
            continue
        assignments.append(
            Assignment(
                prefix=normalized_prefix(row.get("Assignment") or "", prefix_bits),
                prefix_bits=prefix_bits,
                registry=registry,
                organization=organization,
            )
        )
    return assignments


def collect_assignments(source_bytes: dict[str, bytes]) -> list[Assignment]:
    assignments: set[Assignment] = set()
    for registry, (_, _, prefix_bits) in SOURCES.items():
        for assignment in parse_csv(source_bytes[registry], registry, prefix_bits):
            assignments.add(assignment)
    if len(assignments) < 50_000:
        raise ValueError(f"expected at least 50000 assignments, got {len(assignments)}")
    return sorted(assignments)


def source_manifest(
    source_bytes: dict[str, bytes],
    assignments: Iterable[Assignment],
    snapshot_date: str,
) -> dict[str, object]:
    assignment_list = list(assignments)
    sources: list[dict[str, object]] = []
    for registry, (filename, url, prefix_bits) in SOURCES.items():
        registry_count = sum(1 for entry in assignment_list if entry.registry == registry)
        sources.append(
            {
                "registry": registry,
                "filename": filename,
                "url": url,
                "prefixBits": prefix_bits,
                "sha256": sha256(source_bytes[registry]),
                "rowCount": registry_count,
            }
        )
    return {
        "schemaVersion": 1,
        "generatedAt": snapshot_date,
        "authoritativeLandingPage": LANDING_PAGE,
        "redistributionState": "private_pending_permission_review",
        "entryCount": len(assignment_list),
        "sources": sources,
    }


def semantic_manifest(manifest: dict[str, object]) -> dict[str, object]:
    result = dict(manifest)
    result.pop("generatedAt", None)
    return result


def load_existing_manifest(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_database(
    output: Path,
    assignments: list[Assignment],
    manifest: dict[str, object],
) -> None:
    if output.exists():
        output.unlink()
    connection = sqlite3.connect(output)
    try:
        connection.executescript(
            """
            PRAGMA page_size = 4096;
            PRAGMA journal_mode = OFF;
            PRAGMA synchronous = OFF;
            PRAGMA application_id = 1296127563;
            PRAGMA user_version = 1;
            CREATE TABLE metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE assignments (
              prefix TEXT NOT NULL,
              prefix_bits INTEGER NOT NULL,
              registry TEXT NOT NULL,
              organization TEXT NOT NULL,
              PRIMARY KEY (prefix, prefix_bits, registry, organization)
            ) WITHOUT ROWID;
            """
        )
        metadata = {
            "schema_version": str(manifest["schemaVersion"]),
            "generated_at": str(manifest["generatedAt"]),
            "entry_count": str(manifest["entryCount"]),
            "authoritative_landing_page": str(manifest["authoritativeLandingPage"]),
            "sources_json": json.dumps(manifest["sources"], sort_keys=True, separators=(",", ":")),
        }
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        connection.executemany(
            """
            INSERT INTO assignments(prefix, prefix_bits, registry, organization)
            VALUES (?, ?, ?, ?)
            """,
            [
                (entry.prefix, entry.prefix_bits, entry.registry, entry.organization)
                for entry in assignments
            ],
        )
        connection.commit()
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(f"SQLite integrity check failed: {result}")
    finally:
        connection.close()


def update_database(
    input_dir: Path | None,
    output: Path,
    manifest_path: Path,
    snapshot_date: str,
    *,
    check: bool,
) -> tuple[bool, str]:
    source_bytes = load_source_bytes(input_dir)
    assignments = collect_assignments(source_bytes)
    candidate_manifest = source_manifest(source_bytes, assignments, snapshot_date)
    existing_manifest = load_existing_manifest(manifest_path)
    if existing_manifest and semantic_manifest(existing_manifest) == semantic_manifest(candidate_manifest):
        candidate_manifest["generatedAt"] = existing_manifest["generatedAt"]

    with tempfile.TemporaryDirectory() as directory:
        candidate_database = Path(directory) / "mac_address_vendors.sqlite3"
        build_database(candidate_database, assignments, candidate_manifest)
        manifest_bytes = (
            json.dumps(candidate_manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        unchanged = (
            output.exists()
            and manifest_path.exists()
            and output.read_bytes() == candidate_database.read_bytes()
            and manifest_path.read_bytes() == manifest_bytes
        )
        if unchanged:
            return False, "up to date"
        if check:
            return True, "update needed"
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate_database, output)
        manifest_path.write_bytes(manifest_bytes)
    return True, f"wrote {len(assignments)} assignments"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    snapshot_date = args.snapshot_date or datetime.now(timezone.utc).date().isoformat()
    try:
        changed, message = update_database(
            args.input_dir.resolve() if args.input_dir else None,
            args.output.resolve(),
            args.manifest.resolve(),
            snapshot_date,
            check=args.check,
        )
    except (OSError, ValueError, csv.Error, json.JSONDecodeError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(message)
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
