from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import duckdb
import httpx


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))

DEPOT_PATH = Path(os.environ.get("DEPOT_PATH", "~/dev/depot/src")).expanduser()
sys.path.insert(0, str(DEPOT_PATH))

from depot.maps import MapGen


class CoverageMapGen(MapGen):
    """Depot pipeline with multipart buildings normalized before indexing."""

    def process_buildings(self) -> None:
        print("***** Processing Buildings *****")
        cleaned_json = Path(self.city_dir) / "buildings_cleaned.json"
        command = (
            f"node --max-old-space-size={self.RAM} $(which mapshaper) "
            f"{self.buildings_geojson} -proj {self.epsg} -snap 0.5 -clean "
            f"-filter 'this.area > {self.building_index_filter_size}' "
            f"-simplify dp interval={self.building_index_simplification} "
            f"-explode -proj wgs84 -o precision=0.00001 {cleaned_json}"
        )
        self._run_command(command)
        self._convert_to_game_format(str(cleaned_json))
        self.create_buildings_index_binary(str(cleaned_json))


def overture_query(release: str, bbox: list[float], minimum_area: float) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise ValueError(f"Unexpected Overture release tag: {release}")
    west, south, east, north = map(float, bbox)
    source = (
        "s3://overturemaps-us-west-2/release/"
        f"{release}/theme=buildings/type=building/*"
    )
    return f"""
        SELECT geometry, height
        FROM read_parquet('{source}', hive_partitioning=1)
        WHERE bbox.xmin >= {west}
          AND bbox.xmax <= {east}
          AND bbox.ymin >= {south}
          AND bbox.ymax <= {north}
          AND ST_Area_Spheroid(ST_FlipCoordinates(geometry)) > {float(minimum_area)}
    """


def latest_overture_release() -> str:
    response = httpx.get(
        "https://stac.overturemaps.org/catalog.json",
        headers={"User-Agent": "Subway-Builder-Modded/Depot"},
        timeout=30,
    )
    response.raise_for_status()
    release = response.json().get("latest", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise ValueError(f"Unexpected Overture release tag: {release}")
    return release


def prepare_overture_buildings(
    config: dict, output: Path, refresh: bool = True
) -> Path:
    buildings = output / "buildings_prefiltered.geojson"
    release_file = output / "buildings_overture_release.txt"
    release = latest_overture_release()
    cached_release = (
        release_file.read_text(encoding="utf-8").strip()
        if release_file.exists()
        else ""
    )
    if buildings.exists() and cached_release == release and not refresh:
        print(f"Reusing Overture {release} source filter: {buildings}")
        return buildings

    temporary = buildings.with_suffix(".geojson.tmp")
    temporary.unlink(missing_ok=True)
    query = overture_query(release, config["bbox"], 40)
    print(f"Exporting Overture {release} buildings larger than 40 m²...")
    connection = duckdb.connect()
    try:
        connection.execute("LOAD spatial")
        connection.execute("SET enable_progress_bar = false")
        connection.execute(
            f"COPY ({query}) TO '{temporary}' "
            "WITH (FORMAT GDAL, DRIVER 'GeoJSON')"
        )
    finally:
        connection.close()
    temporary.replace(buildings)
    release_file.write_text(f"{release}\n", encoding="utf-8")
    return buildings


def create_generator(
    config: dict, osmpbf: Path, output_root: Path, buildings: Path
) -> MapGen:
    labels = config["labels"]
    ram_gb = int(os.environ.get("DEPOT_RAM_GB", "8"))
    return CoverageMapGen(
        city=config["city"],
        bbox=config["bbox"],
        osmpbf=str(osmpbf),
        outputdir=str(output_root),
        cities=labels["cities"],
        suburbs=labels["suburbs"],
        neighborhoods=labels["neighborhoods"],
        ncores=4,
        RAM=ram_gb,
        buildings_geojson=str(buildings),
        cleanup_files=False,
        create_building_foundations=False,
        create_ocean_foundations=False,
    )


def run_depot_pipeline(generator: MapGen) -> None:
    generator.extract_base_data()
    generator.process_buildings()
    generator.process_roads_and_aeroways()
    generator.generate_pmtiles()
    generator.add_labels()


def main() -> None:
    config = json.loads((ROOT / "config/bue.json").read_text(encoding="utf-8"))
    output_root = ROOT / "output"
    output = output_root / config["city"]
    output.mkdir(parents=True, exist_ok=True)
    osmpbf = Path(os.environ.get("OSM_PBF", config["osmpbf"])).expanduser()
    if not osmpbf.is_absolute():
        osmpbf = ROOT / osmpbf

    refresh = os.environ.get("OVERTURE_REFRESH", "1").lower() not in {
        "0",
        "false",
        "no",
    }
    buildings = prepare_overture_buildings(config, output, refresh=refresh)
    generator = create_generator(config, osmpbf, output_root, buildings)
    run_depot_pipeline(generator)
    output_config = {
        "name": config["name"],
        "code": config["city"],
        "country": config["country"],
        "description": (
            "Buenos Aires metropolitan area map built from OpenStreetMap, "
            "Overture buildings, INDEC Census 2022 employed residents, and "
            "CEP XXI geocoded formal workplace data."
        ),
        "population": 0,
        "bbox": config["bbox"],
        "initialViewState": config["initialViewState"],
        "creator": config["creator"],
        "version": config["version"],
    }
    (output / "config.json").write_text(
        json.dumps(output_config, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
