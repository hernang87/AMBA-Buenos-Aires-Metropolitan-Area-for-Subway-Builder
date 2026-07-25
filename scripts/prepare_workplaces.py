from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare dispersed geocoded workplace establishments for demand generation.")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/workplaces.csv")
    parser.add_argument("--config", type=Path, default=ROOT / "config/bue.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/workplaces.csv")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    workplace_config = config["workplaces"]
    year = int(workplace_config["year"])
    grid_degrees = float(workplace_config["grid_degrees"])
    weights = {str(key): float(value) for key, value in workplace_config["employment_weights"].items()}
    west, south, east, north = config["bbox"]
    grouped: dict[tuple[float, float], dict[str, object]] = {}

    with args.input.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"anio", "lat", "lon", "empleo"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Workplace CSV is missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            if int(row["anio"]) != year:
                continue
            try:
                latitude = float(row["lat"])
                longitude = float(row["lon"])
            except (TypeError, ValueError):
                continue
            if not (west <= longitude <= east and south <= latitude <= north):
                continue
            band = row["empleo"].strip()
            if band not in weights:
                raise ValueError(f"Unknown employment band: {band!r}")
            key = (longitude, latitude)
            group = grouped.setdefault(
                key,
                {"longitude": longitude, "latitude": latitude, "employment_weight": 0.0, "establishments": 0},
            )
            group["employment_weight"] += weights[band]
            group["establishments"] += 1

    if not grouped:
        raise ValueError("No 2022 workplaces matched the AMBA bounding box")

    rows = []
    for index, ((longitude, latitude), group) in enumerate(sorted(grouped.items())):
        grid_lon = math.floor(longitude / grid_degrees)
        grid_lat = math.floor(latitude / grid_degrees)
        rows.append(
            {
                "workplace_id": f"work_{index:06d}",
                "cell_id": f"cell_{grid_lon}_{grid_lat}",
                "longitude": longitude,
                "latitude": latitude,
                "employment_weight": group["employment_weight"],
                "establishments": group["establishments"],
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["workplace_id", "cell_id", "longitude", "latitude", "employment_weight", "establishments"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Prepared {len(rows)} dispersed workplace establishments in {args.output}")


if __name__ == "__main__":
    main()
