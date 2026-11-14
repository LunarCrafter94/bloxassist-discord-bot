"""Regression tests for source-distribution license metadata."""

from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTests(unittest.TestCase):
    def test_configured_license_file_pattern_matches_repository_file(self):
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]
        configuredPatterns = project.get("license-files", [])
        self.assertTrue(
            any(
                candidate.is_file()
                for pattern in configuredPatterns
                for candidate in ROOT.glob(pattern)
            ),
            f"No configured license-files pattern matches a file: {configuredPatterns!r}",
        )
        self.assertTrue((ROOT / "LICENSE.md").is_file())
        self.assertIn("LICENSE.md", configuredPatterns)


if __name__ == "__main__":
    unittest.main()
