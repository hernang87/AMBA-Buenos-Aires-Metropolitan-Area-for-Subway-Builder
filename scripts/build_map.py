from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))

DEPOT_PATH = Path(os.environ.get("DEPOT_PATH", "~/dev/depot/src")).expanduser()
sys.path.insert(0, str(DEPOT_PATH))

from depot.maps import MapGen


def create_generator(config: dict, osmpbf: Path, output_root: Path) -> MapGen:
    labels = config["labels"]
    return MapGen(
        city=config["city"],
        bbox=config["bbox"],
        osmpbf=str(osmpbf),
        outputdir=str(output_root),
        cities=labels["cities"],
        suburbs=labels["suburbs"],
        neighborhoods=labels["neighborhoods"],
        ncores=4,
        RAM=12,
        cleanup_files=False,
        redownload_buildings=True,
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

    generator = create_generator(config, osmpbf, output_root)
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
