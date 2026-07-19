from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]


def representative_point(geometry: dict) -> tuple[float, float]:
    point = shape(geometry).representative_point()
    return point.x, point.y


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(value))


def load_origins(path: Path, grid_degrees: float, bbox: list[float]) -> list[dict[str, float | str | tuple[float, float]]]:
    grouped: dict[tuple[int, int], dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            location = representative_point(json.loads(row["geometry"]))
            population = float(row["population"])
            key = (math.floor(location[0] / grid_degrees), math.floor(location[1] / grid_degrees))
            group = grouped.setdefault(
                key,
                {"population": 0.0, "weighted_lon": 0.0, "weighted_lat": 0.0, "weight": 0.0},
            )
            population_weight = max(population, 1.0)
            group["population"] += population
            group["weighted_lon"] += location[0] * population_weight
            group["weighted_lat"] += location[1] * population_weight
            group["weight"] += population_weight

    if not grouped:
        raise ValueError("No prepared census areas found")

    west, south, east, north = bbox
    return [
        {
            "id": f"origin_{grid_lon}_{grid_lat}",
            "location": (
                min(max(group["weighted_lon"] / group["weight"], west), east),
                min(max(group["weighted_lat"] / group["weight"], south), north),
            ),
            "population": group["population"],
        }
        for (grid_lon, grid_lat), group in sorted(grouped.items())
    ]


def load_workplaces(path: Path) -> list[dict[str, float | str | tuple[float, float]]]:
    workplaces = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            workplaces.append(
                {
                    "id": row["workplace_id"],
                    "location": (float(row["longitude"]), float(row["latitude"])),
                    "employment_weight": float(row["employment_weight"]),
                }
            )
    if not workplaces:
        raise ValueError("No prepared workplace cells found")
    return workplaces


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--areas", type=Path, default=ROOT / "data/processed/areas.csv")
    parser.add_argument("--workplaces", type=Path, default=ROOT / "data/processed/workplaces.csv")
    parser.add_argument("--config", type=Path, default=ROOT / "config/amba.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/AMBA/demand_data.json")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    demand_config = config["demand"]
    decay = float(demand_config["gravity_decay_km"])
    minimum_flow = int(demand_config["minimum_flow"])
    grid_degrees = float(demand_config["grid_degrees"])
    bbox = config.get("bbox", [-180, -90, 180, 90])
    origins = load_origins(args.areas, grid_degrees, bbox)
    workplaces = load_workplaces(args.workplaces)

    points = [
        {"id": origin["id"], "location": list(origin["location"]), "jobs": 0, "residents": 0, "popIds": []}
        for origin in origins
    ] + [
        {"id": workplace["id"], "location": list(workplace["location"]), "jobs": 0, "residents": 0, "popIds": []}
        for workplace in workplaces
    ]
    points_by_id = {point["id"]: point for point in points}
    pops = []

    for origin_index, origin in enumerate(origins):
        resident_count = round(float(origin["population"]))
        weights = [
            float(workplace["employment_weight"])
            * math.exp(-distance_km(origin["location"], workplace["location"]) / decay)
            for workplace in workplaces
        ]
        total_weight = sum(weights)
        if resident_count <= 0 or total_weight <= 0:
            continue
        allocations = [round(resident_count * weight / total_weight) for weight in weights]
        largest_index = max(range(len(allocations)), key=allocations.__getitem__)
        allocations[largest_index] += resident_count - sum(allocations)
        retained = [index for index, size in enumerate(allocations) if size >= minimum_flow]
        if not retained:
            retained = [largest_index]
        discarded = resident_count - sum(allocations[index] for index in retained)
        largest_retained = max(retained, key=allocations.__getitem__)
        allocations[largest_retained] += discarded

        for workplace_index in retained:
            size = allocations[workplace_index]
            workplace = workplaces[workplace_index]
            origin_point = points_by_id[origin["id"]]
            destination_point = points_by_id[workplace["id"]]
            distance = distance_km(origin["location"], workplace["location"])
            pop = {
                "residenceId": origin["id"],
                "jobId": workplace["id"],
                "drivingSeconds": round(distance / 35 * 3600),
                "drivingDistance": round(distance * 1000),
                "size": size,
                "id": f"pop_{origin_index}_{workplace_index}",
            }
            pops.append(pop)
            origin_point["residents"] += size
            destination_point["jobs"] += size
            origin_point["popIds"].append(pop["id"])
            destination_point["popIds"].append(pop["id"])

    points = [point for point in points if point["residents"] or point["jobs"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"points": points, "pops": pops}, separators=(",", ":")), encoding="utf-8")
    config_path = args.output.parent / "config.json"
    if config_path.exists():
        output_config = json.loads(config_path.read_text(encoding="utf-8"))
        output_config["population"] = sum(pop["size"] for pop in pops)
        config_path.write_text(json.dumps(output_config, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(points)} points and {len(pops)} populations in {args.output}")


if __name__ == "__main__":
    main()
