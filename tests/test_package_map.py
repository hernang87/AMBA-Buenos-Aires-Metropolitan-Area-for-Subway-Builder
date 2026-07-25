import unittest

from scripts.package_map import validate_package_identity


class PackageIdentityTests(unittest.TestCase):
    def test_accepts_bue_config_and_pmtiles(self):
        validate_package_identity({"code": "BUE"}, ["config.json", "BUE.pmtiles"])

    def test_rejects_mixed_amba_and_bue_identity(self):
        with self.assertRaisesRegex(ValueError, "code must be BUE"):
            validate_package_identity({"code": "AMBA"}, ["config.json", "BUE.pmtiles"])
        with self.assertRaisesRegex(ValueError, "no AMBA"):
            validate_package_identity(
                {"code": "BUE"},
                ["config.json", "BUE.pmtiles", "AMBA.pmtiles"],
            )


if __name__ == "__main__":
    unittest.main()
