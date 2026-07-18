from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from shapely.geometry import shape


def centroid(geometry: dict) -> tuple[float, float]:
    point = shape(geometry).representative_point()
    return (point.x, point.y)


def distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--areas", type=Path, default=Path("data/processed/areas.csv"))
    parser.add_argument("--config", type=Path, default=Path("config/amba.json"))
    parser.add_argument("--output", type=Path, default=Path("output/AMBA/demand_data.json"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    decay = float(config["demand"]["gravity_decay_km"])
    minimum_flow = int(config["demand"]["minimum_flow"])
    grid_degrees = float(config["demand"].get("grid_degrees", 0))
    bbox = config.get("bbox", [-180, -90, 180, 90])

    def clamp(location: tuple[float, float]) -> tuple[float, float]:
        lon = min(max(location[0], bbox[0]), bbox[2])
        lat = min(max(location[1], bbox[1]), bbox[3])
        return lon, lat

    areas = []
    with args.areas.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            location = centroid(json.loads(row["geometry"]))
            areas.append({"id": row["area_id"], "location": location, "population": float(row["population"]), "jobs": float(row["jobs"])})
    if not areas:
        raise ValueError("No prepared census areas found")
    if grid_degrees > 0:
        grouped = {}
        for area in areas:
            key = (math.floor(area["location"][0] / grid_degrees), math.floor(area["location"][1] / grid_degrees))
            group = grouped.setdefault(key, {"id": f"grid_{key[0]}_{key[1]}", "population": 0.0, "jobs": 0.0, "weighted_lon": 0.0, "weighted_lat": 0.0, "weight": 0.0})
            weight = max(area["population"], 1.0)
            group["population"] += area["population"]
            group["jobs"] += area["jobs"]
            group["weighted_lon"] += area["location"][0] * weight
            group["weighted_lat"] += area["location"][1] * weight
            group["weight"] += weight
            areas = [{"id": group["id"], "location": clamp((group["weighted_lon"] / group["weight"], group["weighted_lat"] / group["weight"])), "population": group["population"], "jobs": group["jobs"]} for group in grouped.values()]
            print(f"Aggregated demand into {len(areas)} grid cells")
    else:
        areas = [{"id": area["id"], "location": clamp(area["location"]), "population": area["population"], "jobs": area["jobs"]} for area in areas]
    points = [{"id": f"area_{area['id']}", "location": list(area["location"]), "jobs": 0, "residents": 0, "popIds": []} for area in areas]
    points_by_id = {point["id"]: point for point in points}
    pops = []
    for origin_index, origin in enumerate(areas):
        resident_count = round(origin["population"])
        weights = [destination["jobs"] * math.exp(-distance_km(origin["location"], destination["location"]) / decay) for destination in areas]
        total_weight = sum(weights)
        if resident_count <= 0 or total_weight <= 0:
            continue
        allocations = [round(resident_count * weight / total_weight) for weight in weights]
        allocations[origin_index] += resident_count - sum(allocations)
        retained = [index for index, size in enumerate(allocations) if size >= minimum_flow]
        if not retained:
            retained = [max(range(len(allocations)), key=allocations.__getitem__)]
        discarded = resident_count - sum(allocations[index] for index in retained)
        largest_retained = max(retained, key=allocations.__getitem__)
        allocations[largest_retained] += discarded
        for destination_index, size in enumerate(allocations):
            if destination_index not in retained:
                continue
            origin_point = points[origin_index]
            destination_point = points[destination_index]
            distance = distance_km(origin_point["location"], destination_point["location"])
            pop = {"residenceId": origin_point["id"], "jobId": destination_point["id"], "drivingSeconds": round(distance / 35 * 3600), "drivingDistance": round(distance * 1000), "size": size, "id": f"pop_{origin_index}_{destination_index}"}
            pops.append(pop)
            points_by_id[pop["residenceId"]]["residents"] += size
            points_by_id[pop["jobId"]]["jobs"] += size
            points_by_id[pop["residenceId"]]["popIds"].append(pop["id"])
            if pop["jobId"] != pop["residenceId"]:
                points_by_id[pop["jobId"]]["popIds"].append(pop["id"])
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
