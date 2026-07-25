import unittest

from scripts.build_map import CoverageMapGen, overture_query, run_depot_pipeline


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
    def test_building_processor_explodes_multipart_geometry_before_indexes(self):
        class FakeCoverageMap:
            city_dir = "/tmp/BUE"
            buildings_geojson = "/tmp/buildings.geojson"
            epsg = "epsg:32721"
            RAM = 8000
            building_index_filter_size = 40
            building_index_simplification = 1

            def __init__(self):
                self.calls = []

            def _run_command(self, command):
                self.calls.append(("command", command))

            def _convert_to_game_format(self, path):
                self.calls.append(("json", path))

            def create_buildings_index_binary(self, path):
                self.calls.append(("binary", path))

        generator = FakeCoverageMap()
        CoverageMapGen.process_buildings(generator)

        self.assertIn("-explode", generator.calls[0][1])
        self.assertEqual("json", generator.calls[1][0])
        self.assertEqual("binary", generator.calls[2][0])

    def test_overture_query_filters_at_depot_building_threshold(self):
        query = overture_query(
            "2026-07-22.0", [-59.4, -35.2, -57.7, -34.2], 40
        )

        self.assertIn(
            "ST_Area_Spheroid(ST_FlipCoordinates(geometry)) > 40.0", query
        )
        self.assertIn("SELECT geometry, height", query)
        self.assertNotIn("SELECT id", query)

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
