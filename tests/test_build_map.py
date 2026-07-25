import unittest

from scripts.build_map import run_depot_pipeline


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def extract_base_data(self):
        self.calls.append("extract_base_data")

    def process_buildings(self):
        self.calls.append("process_buildings")

    def process_roads_and_aeroways(self):
        self.calls.append("process_roads_and_aeroways")

    def generate_pmtiles(self):
        self.calls.append("generate_pmtiles")

    def add_labels(self):
        self.calls.append("add_labels")


class DepotPipelineTests(unittest.TestCase):
    def test_runs_native_building_processing_before_pmtiles(self):
        generator = FakeGenerator()

        run_depot_pipeline(generator)

        self.assertEqual(
            [
                "extract_base_data",
                "process_buildings",
                "process_roads_and_aeroways",
                "generate_pmtiles",
                "add_labels",
            ],
            generator.calls,
        )


if __name__ == "__main__":
    unittest.main()
