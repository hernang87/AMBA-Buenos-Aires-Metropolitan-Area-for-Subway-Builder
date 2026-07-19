from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare geocoded workplace cells for demand generation.")
    parser.add_argument("--input", type=Path, default=ROOT / "data/raw/workplaces.csv")
    parser.add_argument("--config", type=Path, default=ROOT / "config/amba.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/workplaces.csv")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    workplace_config = config["workplaces"]
    year = int(workplace_config["year"])
    grid_degrees = float(workplace_config["grid_degrees"])
    weights = {str(key): float(value) for key, value in workplace_config["employment_weights"].items()}
    west, south, east, north = config["bbox"]
    grouped: dict[tuple[int, int], dict[str, float]] = {}

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
            key = (math.floor(longitude / grid_degrees), math.floor(latitude / grid_degrees))
            group = grouped.setdefault(
                key,
                {"employment_weight": 0.0, "establishments": 0.0, "weighted_lon": 0.0, "weighted_lat": 0.0},
            )
            employment_weight = weights[band]
            group["employment_weight"] += employment_weight
            group["establishments"] += 1
            group["weighted_lon"] += longitude * employment_weight
            group["weighted_lat"] += latitude * employment_weight

    if not grouped:
        raise ValueError("No 2022 workplaces matched the AMBA bounding box")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["workplace_id", "longitude", "latitude", "employment_weight", "establishments"],
        )
        writer.writeheader()
        for index, ((grid_lon, grid_lat), group) in enumerate(sorted(grouped.items())):
            weight = group["employment_weight"]
            writer.writerow(
                {
                    "workplace_id": f"work_{grid_lon}_{grid_lat}",
                    "longitude": group["weighted_lon"] / weight,
                    "latitude": group["weighted_lat"] / weight,
                    "employment_weight": weight,
                    "establishments": int(group["establishments"]),
                }
            )
    print(f"Prepared {len(grouped)} workplace cells in {args.output}")


if __name__ == "__main__":
    main()
