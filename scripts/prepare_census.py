from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


AMBA_BBOX = (-59.4, -35.2, -57.7, -34.2)


def area_id(properties: dict) -> str:
    for key in ("area_id", "cod_indec", "id", "cod_rad"):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    raise ValueError("Each geometry needs area_id, cod_indec, id, or cod_rad")


def coordinate_bounds(geometry: dict) -> tuple[float, float, float, float]:
    def points(value):
        if isinstance(value[0], (int, float)):
            yield value
        else:
            for child in value:
                yield from points(child)

    coordinates = list(points(geometry["coordinates"]))
    longitudes = [point[0] for point in coordinates]
    latitudes = [point[1] for point in coordinates]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def to_wgs84(value):
    if isinstance(value[0], (int, float)):
        x, y = value
        longitude = x / 20037508.34 * 180
        latitude = math.degrees(2 * math.atan(math.exp(math.radians(y / 20037508.34 * 180))) - math.pi / 2)
        return [longitude, latitude]
    return [to_wgs84(child) for child in value]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--areas", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.areas.read_text(encoding="utf-8"))
    stats = {}
    with args.stats.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = row["area_id"].strip()
            population = float(row["population"])
            jobs = float(row["jobs"])
            if population < 0 or jobs < 0:
                raise ValueError(f"Negative population/jobs for {key}")
            stats[key] = (population, jobs)
    output = []
    for feature in source.get("features", []):
        properties = feature.get("properties") or {}
        key = area_id(properties)
        geometry = feature.get("geometry") or {}
        if geometry.get("coordinates") and geometry.get("type") in {"Polygon", "MultiPolygon"}:
            geometry = {**geometry, "coordinates": to_wgs84(geometry["coordinates"])}
        bounds = coordinate_bounds(geometry) if geometry.get("coordinates") else None
        overlaps_amba = bounds and not (bounds[2] < AMBA_BBOX[0] or bounds[0] > AMBA_BBOX[2] or bounds[3] < AMBA_BBOX[1] or bounds[1] > AMBA_BBOX[3])
        if key not in stats or geometry.get("type") not in {"Polygon", "MultiPolygon"} or not overlaps_amba:
            continue
        population, jobs = stats[key]
        output.append({"area_id": key, "population": population, "jobs": jobs, "geometry": geometry})
    if not output:
        raise ValueError("No geometry/statistics identifiers matched")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["area_id", "population", "jobs", "geometry"])
        writer.writeheader()
        for row in output:
            writer.writerow({**row, "geometry": json.dumps(row["geometry"], separators=(",", ":"))})
    print(f"Prepared {len(output)} census areas in {args.output}")


if __name__ == "__main__":
    main()
