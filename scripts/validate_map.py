from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "output/AMBA"
def validate_demand(
    config: dict,
    demand: dict,
    maximum_population_size: int,
    maximum_population_count: int,
    allowed_job_locations: set[tuple[float, float]] | None = None,
    expected_point_count: int | None = None,
) -> dict[str, int]:
    bbox = config.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("config.json has an invalid bbox")
    point_list = demand.get("points", [])
    populations = demand.get("pops", [])
    if not point_list or not populations:
        raise ValueError("Demand data is empty")
    if len(populations) > maximum_population_count:
        raise ValueError(f"Population count exceeds {maximum_population_count}: {len(populations)}")
    if expected_point_count is not None and len(point_list) != expected_point_count:
        raise ValueError(f"Demand point count must be {expected_point_count}: {len(point_list)}")

    points = {point["id"]: point for point in point_list}
    if len(points) != len(point_list):
        raise ValueError("Demand point IDs are not unique")
    coordinates = [tuple(point["location"]) for point in point_list]
    if len(coordinates) != len(set(coordinates)):
        raise ValueError("Duplicate demand point coordinate")
    if allowed_job_locations is not None:
        invalid_job_locations = {
            tuple(point["location"])
            for point in point_list
            if point["jobs"] and tuple(point["location"]) not in allowed_job_locations
        }
        if invalid_job_locations:
            location = min(invalid_job_locations)
            raise ValueError(f"Job coordinate is not a census-derived demand zone: {location}")

    populations_by_id = {pop["id"]: pop for pop in populations}
    if len(populations_by_id) != len(populations):
        raise ValueError("Population IDs are not unique")
    expected_pop_ids: dict[str, list[str]] = defaultdict(list)
    expected_residents: dict[str, int] = defaultdict(int)
    expected_jobs: dict[str, int] = defaultdict(int)
    resident_total = 0
    job_total = 0
    for pop in populations:
        if pop["residenceId"] not in points or pop["jobId"] not in points:
            raise ValueError(f"Invalid demand reference: {pop['id']}")
        if pop["size"] <= 0:
            raise ValueError(f"Non-positive population size: {pop['id']}")
        if pop["size"] > maximum_population_size:
            raise ValueError(f"Population size exceeds {maximum_population_size}: {pop['id']}")
        resident_total += pop["size"]
        job_total += pop["size"]
        expected_pop_ids[pop["residenceId"]].append(pop["id"])
        expected_residents[pop["residenceId"]] += pop["size"]
        expected_jobs[pop["jobId"]] += pop["size"]
        if pop["jobId"] != pop["residenceId"]:
            expected_pop_ids[pop["jobId"]].append(pop["id"])
    for point in points.values():
        longitude, latitude = point["location"]
        if not bbox[0] <= longitude <= bbox[2] or not bbox[1] <= latitude <= bbox[3]:
            raise ValueError(f"Demand point outside bbox: {point['id']}")
        actual_pop_ids = point.get("popIds", [])
        if len(actual_pop_ids) != len(set(actual_pop_ids)):
            raise ValueError(f"Point popIds contain duplicates: {point['id']}")
        if sorted(actual_pop_ids) != sorted(expected_pop_ids[point["id"]]):
            raise ValueError(f"Point popIds do not reconcile: {point['id']}")
        if point["residents"] != expected_residents[point["id"]]:
            raise ValueError(f"Point resident total does not reconcile: {point['id']}")
        if point["jobs"] != expected_jobs[point["id"]]:
            raise ValueError(f"Point job total does not reconcile: {point['id']}")
    if sum(point["residents"] for point in points.values()) != resident_total:
        raise ValueError("Resident totals do not reconcile")
    if sum(point["jobs"] for point in points.values()) != job_total:
        raise ValueError("Job totals do not reconcile")
    if config.get("population") != resident_total:
        raise ValueError("config.json population does not reconcile")
    return {"points": len(points), "populations": len(populations), "population": resident_total}


def validate_report(
    report: dict,
    maximum_population_count: int,
    expected_point_count: int | None = None,
) -> None:
    model = report.get("model", {})
    output = report.get("output", {})
    if output.get("duplicate_coordinates") != 0:
        raise ValueError("Demand report contains duplicate coordinates")
    if output.get("populations", maximum_population_count + 1) > maximum_population_count:
        raise ValueError(f"Demand report population count exceeds {maximum_population_count}")
    if expected_point_count is not None and output.get("points") != expected_point_count:
        raise ValueError(f"Demand report point count must be {expected_point_count}")
    if output.get("points", 0) <= model.get("solver_zones", 0) * 3:
        raise ValueError("Display clusters are not sufficiently denser than solver zones")
    if abs(
        model.get("exported_formal_mean_km", float("inf"))
        - model.get("dense_formal_mean_km", 0)
    ) > 2:
        raise ValueError("Exported formal mean commute drift exceeds 2 km")
    if abs(
        model.get("exported_formal_p90_km", float("inf"))
        - model.get("dense_formal_p90_km", 0)
    ) > 5:
        raise ValueError("Exported formal p90 commute drift exceeds 5 km")


def main() -> None:
    config = json.loads((MAP / "config.json").read_text(encoding="utf-8"))
    demand = json.loads((MAP / "demand_data.json").read_text(encoding="utf-8"))
    report = json.loads((MAP / "demand_report.json").read_text(encoding="utf-8"))
    source_config = json.loads((ROOT / "config/amba.json").read_text(encoding="utf-8"))
    required = [
        "AMBA.pmtiles",
        "roads.geojson",
        "runways_taxiways.geojson",
        "buildings_index.json",
        "buildings_index.bin",
        "config.json",
        "demand_data.json",
        "demand_report.json",
    ]
    missing = [name for name in required if not (MAP / name).exists()]
    if missing:
        raise SystemExit(f"Missing map files: {', '.join(missing)}")
    if config.get("code") != "AMBA":
        raise SystemExit("config.json must use code AMBA")
    allowed_job_locations = {
        tuple(point["location"])
        for point in demand["points"]
        if str(point["id"]).startswith("origin_")
    }
    expected_point_count = int(source_config["demand"]["display_cluster_count"])
    try:
        summary = validate_demand(
            config,
            demand,
            int(source_config["demand"]["maximum_population_size"]),
            int(source_config["demand"]["maximum_population_count"]),
            allowed_job_locations,
            expected_point_count,
        )
        validate_report(
            report,
            int(source_config["demand"]["maximum_population_count"]),
            expected_point_count,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(
        f"Validated AMBA: {summary['points']} points, "
        f"{summary['populations']} populations, {summary['population']} employed residents"
    )


if __name__ == "__main__":
    main()
