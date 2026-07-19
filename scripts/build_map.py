from __future__ import annotations

import json
import os
import sys
import subprocess
import shutil
import sqlite3
import types
import re
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))
home_dir = Path(os.environ.get("HOME", str(ROOT / ".home"))).expanduser()
if not os.access(home_dir, os.W_OK):
    local_home = ROOT / ".home"
    local_home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(local_home)

DEPOT_PATH = Path(os.environ.get("DEPOT_PATH", "~/dev/depot/src")).expanduser()
sys.path.insert(0, str(DEPOT_PATH))

from depot.maps import MapGen


def build_buildings_index(generator: MapGen, buildings_geojson: Path, cleaned_json: Path, minimum_area: float) -> None:
    gdf = gpd.read_file(buildings_geojson)
    if gdf.empty:
        raise RuntimeError(f"No buildings found in {buildings_geojson}")
    gdf = gdf[gdf.geometry.notna()]
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if gdf.empty:
        raise RuntimeError(f"No polygon buildings found in {buildings_geojson}")
    projected = gdf.to_crs(generator.epsg)
    projected = projected[projected.geometry.area > minimum_area]
    if projected.empty:
        raise RuntimeError(f"No buildings above {minimum_area} m2 in {buildings_geojson}")
    projected = projected.copy()
    keep_columns = [column for column in ["height"] if column in projected.columns]
    projected = projected[keep_columns + ["geometry"]]
    if "height" in projected.columns:
        projected["height"] = projected["height"].apply(
            lambda value: float(match.group(0))
            if isinstance(value, str) and (match := re.search(r"[-+]?\d*\.?\d+", value))
            else value
        )
    projected["geometry"] = projected.geometry.simplify(1, preserve_topology=True)
    projected = projected.to_crs("EPSG:4326")
    projected.to_file(cleaned_json, driver="GeoJSON")
    generator._convert_to_game_format(str(cleaned_json))
    generator.create_buildings_index_binary(str(cleaned_json))


def patch_generator(generator: MapGen, cleaned_json: Path) -> None:
    def fix_mbtiles_sequential(self: MapGen) -> None:
        path_prefix = os.path.join(self.city_dir, self.city.lower())
        input_path = f"{path_prefix}-clean.mbtiles"
        output_path = f"{path_prefix}-fixed.mbtiles"

        if os.path.exists(output_path):
            os.remove(output_path)

        if self.verb:
            print(f"***** Fixing MBTiles for {self.city} *****")
        conn = sqlite3.connect(input_path)
        cursor = conn.cursor()
        cursor.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles")
        all_tiles = cursor.fetchall()

        if self.verb:
            print(f"Processing {len(all_tiles)} tiles using 1 core...")

        results = [self._process_tile_worker(tile) for tile in all_tiles]

        out_conn = sqlite3.connect(output_path)
        out_conn.execute("CREATE TABLE metadata (name text, value text)")
        out_conn.execute(
            "CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)"
        )
        cursor.execute("SELECT name, value FROM metadata")
        out_conn.executemany("INSERT INTO metadata VALUES (?, ?)", cursor.fetchall())
        out_conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", results)
        out_conn.execute("UPDATE metadata SET value = REPLACE(value, 'class', 'kind') WHERE name = 'json'")
        out_conn.execute("UPDATE metadata SET value = REPLACE(value, 'subclass', 'kind') WHERE name = 'json'")
        out_conn.commit()
        out_conn.close()
        conn.close()
        if self.verb:
            print(f"Successfully created fixed MBTiles at {output_path}")

    def generate_building_tiles_fast(self: MapGen) -> None:
        if self.verb:
            print("***** Generating Building Overlays *****")

        self.buildings_mbtiles = os.path.join(self.city_dir, "buildings.mbtiles")
        self.buildings_zoom_geojson = os.path.join(self.city_dir, "buildings_zoom.geojson")
        shutil.copyfile(cleaned_json, self.buildings_zoom_geojson)
        with open(self.buildings_zoom_geojson, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        for feature in data.get("features", []):
            properties = feature.setdefault("properties", {})
            value = properties.get("height")
            if isinstance(value, str):
                match = re.search(r"[-+]?\d*\.?\d+", value)
                if match:
                    properties["height"] = float(match.group(0))
                else:
                    properties.pop("height", None)
        with open(self.buildings_zoom_geojson, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self._set_default_building_height()

        if self.max_building_tile_size is not None:
            building_tile_params = [
                "--drop-smallest-as-needed",
                f"--maximum-tile-bytes={self.max_building_tile_size}",
            ]
        else:
            building_tile_params = ["--no-tile-size-limit"]

        tippe_cmd = [
            "tippecanoe",
            "-o",
            self.buildings_mbtiles,
            "--layer=buildings",
            "--include=height",
            *building_tile_params,
            "-Z12",
            f"-z{self.maxzoom}",
            self.buildings_zoom_geojson,
            "--force",
        ]
        self._run_command(tippe_cmd)

    generator.fix_mbtiles = types.MethodType(fix_mbtiles_sequential, generator)
    generator._generate_building_tiles = types.MethodType(generate_building_tiles_fast, generator)


def main() -> None:
    config = json.loads((ROOT / "config/amba.json").read_text(encoding="utf-8"))
    output_root = ROOT / "output"
    output = output_root / "AMBA"
    output.mkdir(parents=True, exist_ok=True)
    osmpbf = Path(os.environ.get("OSM_PBF", config["osmpbf"])).expanduser()
    if not osmpbf.is_absolute():
        osmpbf = ROOT / osmpbf
    labels = config["labels"]
    generator = MapGen(city=config["city"], bbox=config["bbox"], osmpbf=str(osmpbf), outputdir=str(output_root), cities=labels["cities"], suburbs=labels["suburbs"], neighborhoods=labels["neighborhoods"], ncores=4, RAM=12, cleanup_files=False, create_building_foundations=False, create_ocean_foundations=False)
    generator.extract_base_data()
    city_pbf = output / f"{config['city'].lower()}.osm.pbf"
    buildings_pbf = output / "buildings.osm.pbf"
    buildings_geojson = output / "buildings.geojson"
    if not buildings_geojson.exists():
        subprocess.run([
            "osmium", "tags-filter", str(city_pbf), "wr/building",
            "-o", str(buildings_pbf), "--overwrite"
        ], check=True)
        subprocess.run([
            "osmium", "export", str(buildings_pbf),
            "-o", str(buildings_geojson),
            "--geometry-types=polygon",
            "--overwrite",
        ], check=True)
    cleaned_json = output / "buildings_cleaned.json"
    build_buildings_index(generator, buildings_geojson, cleaned_json, generator.building_index_filter_size)
    patch_generator(generator, cleaned_json)
    generator.process_roads_and_aeroways()
    generator.generate_pmtiles()
    generator.add_labels()
    output_config = {
        "name": config["name"],
        "code": config["city"],
        "country": config["country"],
        "description": "Buenos Aires metropolitan area map built from OpenStreetMap, INDEC Census 2022 population, and CEP XXI geocoded formal workplace data.",
        "population": 0,
        "bbox": config["bbox"],
        "initialViewState": config["initialViewState"],
        "creator": config["creator"],
        "version": config["version"],
    }
    (output / "config.json").write_text(json.dumps(output_config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
