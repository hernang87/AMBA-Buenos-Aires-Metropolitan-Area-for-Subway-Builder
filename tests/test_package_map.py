import unittest

from scripts.package_map import validate_package_identity


class PackageIdentityTests(unittest.TestCase):
    def test_accepts_bue_config_and_pmtiles(self):
        validate_package_identity(
            {"code": "BUE", "version": "0.3.1"},
            ["config.json", "BUE.pmtiles", "buildings_index.bin"],
            "0.3.1",
        )

    def test_rejects_mixed_amba_and_bue_identity(self):
        with self.assertRaisesRegex(ValueError, "code must be BUE"):
            validate_package_identity({"code": "AMBA"}, ["config.json", "BUE.pmtiles"], "0.3.1")
        with self.assertRaisesRegex(ValueError, "no AMBA"):
            validate_package_identity(
                {"code": "BUE"},
                ["config.json", "BUE.pmtiles", "AMBA.pmtiles"],
                "0.3.1",
            )

    def test_requires_binary_only_and_matching_version(self):
        with self.assertRaisesRegex(ValueError, "only the binary"):
            validate_package_identity(
                {"code": "BUE", "version": "0.3.1"},
                ["BUE.pmtiles", "buildings_index.json"],
                "0.3.1",
            )
        with self.assertRaisesRegex(ValueError, "version must be 0.3.1"):
            validate_package_identity(
                {"code": "BUE", "version": "0.3.0"},
                ["BUE.pmtiles", "buildings_index.bin"],
                "0.3.1",
            )


if __name__ == "__main__":
    unittest.main()
