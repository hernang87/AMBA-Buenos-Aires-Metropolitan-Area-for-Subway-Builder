import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import package_map

validate_package_identity = package_map.validate_package_identity


class PackageIdentityTests(unittest.TestCase):
    def test_accepts_bue_config_and_pmtiles(self):
        validate_package_identity(
            {"code": "BUE", "version": "1.0.0"},
            ["config.json", "BUE.pmtiles", "buildings_index.bin"],
            "1.0.0",
        )

    def test_rejects_mixed_amba_and_bue_identity(self):
        with self.assertRaisesRegex(ValueError, "code must be BUE"):
            validate_package_identity({"code": "AMBA"}, ["config.json", "BUE.pmtiles"], "1.0.0")
        with self.assertRaisesRegex(ValueError, "no AMBA"):
            validate_package_identity(
                {"code": "BUE"},
                ["config.json", "BUE.pmtiles", "AMBA.pmtiles"],
                "1.0.0",
            )

    def test_requires_binary_only_and_matching_version(self):
        with self.assertRaisesRegex(ValueError, "only the binary"):
            validate_package_identity(
                {"code": "BUE", "version": "1.0.0"},
                ["BUE.pmtiles", "buildings_index.json"],
                "1.0.0",
            )
        with self.assertRaisesRegex(ValueError, "version must be 1.0.0"):
            validate_package_identity(
                {"code": "BUE", "version": "0.9.0"},
                ["BUE.pmtiles", "buildings_index.bin"],
                "1.0.0",
            )

    def test_packaging_writes_registry_release_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            city = root / "output/BUE"
            city.mkdir(parents=True)
            (root / "config").mkdir()
            (root / "config/bue.json").write_text('{"version":"1.0.0"}')
            (city / "config.json").write_text('{"code":"BUE","version":"1.0.0"}')
            for name in (
                "BUE.pmtiles", "buildings_index.bin", "demand_data.json",
                "roads.geojson", "runways_taxiways.geojson",
            ):
                (city / name).write_bytes(b"test")

            with patch.object(package_map, "ROOT", root), patch.object(package_map, "MAP", city):
                package_map.main()

            manifest = json.loads((root / "output/manifest.json").read_text())
            self.assertEqual(">=1.7.1", manifest["dependencies"]["subway-builder"])
            with zipfile.ZipFile(root / "output/amba.zip") as archive:
                self.assertNotIn("manifest.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
