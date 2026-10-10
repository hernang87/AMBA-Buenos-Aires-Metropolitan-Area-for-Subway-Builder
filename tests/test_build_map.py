import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build_map
from scripts.build_map import (
    CoverageMapGen,
    create_generator,
    game_area_layers,
    overture_query,
    resolve_osmpbf,
    run_depot_pipeline,
)


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
    def test_translates_parks_and_airports_to_the_game_layers(self):
        polygon = {"type": "Polygon", "coordinates": [[
            [100, 100], [900, 100], [900, 900], [100, 900], [100, 100]
        ]]}
        layers = {
            "commercial": {"features": [{"geometry": polygon, "properties": {"kind": "commercial"}}],
                           "extent": 4096, "version": 2},
            "landuse": {"features": [
                {"geometry": polygon, "properties": {"kind": "park"}},
                {"geometry": polygon, "properties": {"kind": "aerodrome"}},
            ], "extent": 4096, "version": 2},
        }

        translated = {layer["name"]: layer for layer in game_area_layers(layers, 12, 1600)}

        self.assertEqual({"commercial", "parks", "airports"}, set(translated))
        self.assertGreater(translated["parks"]["features"][0]["properties"]["area"], 100000)

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


class OsmPbfResolutionTests(unittest.TestCase):
    def test_root_file_wins_over_data_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/raw").mkdir(parents=True)
            (root / "data/raw/extract.osm.pbf").write_bytes(b"raw")
            (root / "extract.osm.pbf").write_bytes(b"root")

            resolved = resolve_osmpbf({"osmpbf": "extract.osm.pbf"}, root, {})

            self.assertEqual(root / "extract.osm.pbf", resolved)

    def test_falls_back_to_data_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data/raw").mkdir(parents=True)
            (root / "data/raw/extract.osm.pbf").write_bytes(b"raw")

            resolved = resolve_osmpbf({"osmpbf": "extract.osm.pbf"}, root, {})

            self.assertEqual(root / "data/raw/extract.osm.pbf", resolved)

    def test_osm_pbf_env_relative_path_resolves_against_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maps").mkdir()
            (root / "maps/custom.osm.pbf").write_bytes(b"custom")

            resolved = resolve_osmpbf(
                {"osmpbf": "extract.osm.pbf"}, root, {"OSM_PBF": "maps/custom.osm.pbf"}
            )

            self.assertEqual(root / "maps/custom.osm.pbf", resolved)

    def test_raises_system_exit_when_nothing_found(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaises(SystemExit):
                resolve_osmpbf({"osmpbf": "missing.osm.pbf"}, root, {})


class CreateGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "city": "BUE",
            "bbox": [-59.4, -35.2, -57.7, -34.2],
            "labels": {"cities": ["city"], "suburbs": ["suburb"], "neighborhoods": ["quarter"]},
            "depot": {"ncores": 4},
        }

    def _create(self):
        created = []

        class RecordingGenerator:
            def __init__(self, **kwargs):
                created.append(kwargs)

        with patch.object(build_map, "MapGen", object), \
                patch.object(build_map, "CoverageMapGen", RecordingGenerator):
            create_generator(self.config, Path("x.pbf"), Path("out"), Path("b.geojson"))
        return created[-1]

    def test_passes_ncores_from_config(self):
        with patch.dict(os.environ):
            os.environ.pop("DEPOT_NCORES", None)
            kwargs = self._create()

        self.assertEqual(4, kwargs["ncores"])

    def test_depot_ncores_env_overrides_config(self):
        with patch.dict(os.environ, {"DEPOT_NCORES": "6"}):
            kwargs = self._create()

        self.assertEqual(6, kwargs["ncores"])


if __name__ == "__main__":
    unittest.main()
