from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import config_slice


SAMPLE = {
    "city": "BUE",
    "name": "Buenos Aires",
    "bbox": [-58.5, -34.7, -58.3, -34.5],
    "version": "1.0",
    "registry": {"id": "bue"},
    "demand": {"gravity": 2},
    "workplaces": {"year": 2022},
    "labels": ["a"],
    "osmpbf": "argentina-latest.osm.pbf",
}


class ConfigSliceContentTest(unittest.TestCase):
    def test_build_slice_excludes_demand_workplaces_version_registry(self) -> None:
        self.assertEqual(
            config_slice.slice_config(SAMPLE, "build"),
            {
                "city": "BUE",
                "name": "Buenos Aires",
                "bbox": [-58.5, -34.7, -58.3, -34.5],
                "labels": ["a"],
                "osmpbf": "argentina-latest.osm.pbf",
            },
        )

    def test_demand_slice(self) -> None:
        self.assertEqual(
            config_slice.slice_config(SAMPLE, "demand"),
            {"demand": {"gravity": 2}, "bbox": [-58.5, -34.7, -58.3, -34.5], "version": "1.0"},
        )

    def test_workplaces_slice(self) -> None:
        self.assertEqual(
            config_slice.slice_config(SAMPLE, "workplaces"),
            {"workplaces": {"year": 2022}, "bbox": [-58.5, -34.7, -58.3, -34.5]},
        )

    def test_unknown_name_exits(self) -> None:
        with self.assertRaises(SystemExit):
            config_slice.slice_config(SAMPLE, "nope")


class ConfigSliceCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.config_path = self.dir / "bue.json"
        self.config_path.write_text(json.dumps(SAMPLE), encoding="utf-8")
        self.output = self.dir / "out" / "demand.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, name: str = "demand") -> None:
        argv = ["config_slice.py", name, str(self.output), "--config", str(self.config_path)]
        saved = sys.argv
        sys.argv = argv
        try:
            config_slice.main()
        finally:
            sys.argv = saved

    def test_writes_expected_content(self) -> None:
        self._run("demand")
        expected = json.dumps(config_slice.slice_config(SAMPLE, "demand"), indent=2, sort_keys=True) + "\n"
        self.assertEqual(self.output.read_text(encoding="utf-8"), expected)

    def test_identical_rewrite_preserves_mtime(self) -> None:
        self._run("demand")
        old_ns = 1_000_000_000_000_000_000
        os.utime(self.output, ns=(old_ns, old_ns))
        self._run("demand")
        self.assertEqual(self.output.stat().st_mtime_ns, old_ns)

    def test_changed_input_rewrites(self) -> None:
        self._run("demand")
        old_ns = 1_000_000_000_000_000_000
        os.utime(self.output, ns=(old_ns, old_ns))
        changed = dict(SAMPLE, demand={"gravity": 3})
        self.config_path.write_text(json.dumps(changed), encoding="utf-8")
        self._run("demand")
        self.assertNotEqual(self.output.stat().st_mtime_ns, old_ns)
        self.assertIn('"gravity": 3', self.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
