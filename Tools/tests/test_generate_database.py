import csv
import importlib.util
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "generate_database.py"
SPEC = importlib.util.spec_from_file_location("generate_database", MODULE_PATH)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def csv_bytes(registry: str, assignment: str, organization: str) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Registry", "Assignment", "Organization Name", "Organization Address"])
    writer.writerow([registry, assignment, organization, "Example address"])
    return stream.getvalue().encode()


class GenerateDatabaseTests(unittest.TestCase):
    def test_parses_each_registry_prefix_width(self):
        samples = {
            "MA-L": ("0016CB", 24),
            "MA-M": ("C85CE27", 28),
            "MA-S": ("8C1F64AFA", 36),
            "IAB": ("40D8550D7", 36),
        }
        for registry, (assignment, bits) in samples.items():
            parsed = generator.parse_csv(
                csv_bytes(registry, assignment, f"{registry} Vendor"),
                registry,
                bits,
            )
            self.assertEqual(parsed[0].prefix, assignment)
            self.assertEqual(parsed[0].prefix_bits, bits)

    def test_builds_queryable_database(self):
        assignments = [
            generator.Assignment("0016CB", 24, "MA-L", "Apple, Inc."),
            generator.Assignment("0016CB1", 28, "MA-M", "More Specific Vendor"),
        ]
        manifest = {
            "schemaVersion": 1,
            "generatedAt": "2026-07-17",
            "entryCount": 2,
            "authoritativeLandingPage": generator.LANDING_PAGE,
            "sources": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "test.sqlite3"
            generator.build_database(database_path, assignments, manifest)
            connection = sqlite3.connect(database_path)
            try:
                row = connection.execute(
                    "SELECT organization FROM assignments WHERE prefix = ?",
                    ("0016CB1",),
                ).fetchone()
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
            finally:
                connection.close()
        self.assertEqual(row, ("More Specific Vendor",))
        self.assertEqual(integrity, ("ok",))

    def test_rejects_wrong_prefix_width(self):
        with self.assertRaises(ValueError):
            generator.normalized_prefix("0016CB", 28)


if __name__ == "__main__":
    unittest.main()
