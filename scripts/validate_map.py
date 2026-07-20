from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "output/AMBA"
MAX_DEMAND_SIZE = 200


def main() -> None:
    config = json.loads((MAP / "config.json").read_text(encoding="utf-8"))
    demand = json.loads((MAP / "demand_data.json").read_text(encoding="utf-8"))
    required = ["AMBA.pmtiles", "roads.geojson", "runways_taxiways.geojson", "buildings_index.json", "buildings_index.bin", "config.json", "demand_data.json"]
    missing = [name for name in required if not (MAP / name).exists()]
    if missing:
        raise SystemExit(f"Missing map files: {', '.join(missing)}")
    if config.get("code") != "AMBA":
        raise SystemExit("config.json must use code AMBA")
    bbox = config.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise SystemExit("config.json has an invalid bbox")
    points = {point["id"]: point for point in demand.get("points", [])}
    if not points or not demand.get("pops"):
        raise SystemExit("Demand data is empty")
    resident_total = 0
    job_total = 0
    for pop in demand["pops"]:
        if pop["residenceId"] not in points or pop["jobId"] not in points:
            raise SystemExit(f"Invalid demand reference: {pop['id']}")
        if pop["size"] <= 0:
            raise SystemExit(f"Non-positive demand size: {pop['id']}")
        if pop["size"] > MAX_DEMAND_SIZE:
            raise SystemExit(f"Demand size exceeds {MAX_DEMAND_SIZE}: {pop['id']}")
        resident_total += pop["size"]
        job_total += pop["size"]
    for point in points.values():
        if point["jobs"] > MAX_DEMAND_SIZE:
            raise SystemExit(f"Job point exceeds {MAX_DEMAND_SIZE}: {point['id']}")
        longitude, latitude = point["location"]
        if not bbox[0] <= longitude <= bbox[2] or not bbox[1] <= latitude <= bbox[3]:
            raise SystemExit(f"Demand point outside bbox: {point['id']}")
    if sum(point["residents"] for point in points.values()) != resident_total:
        raise SystemExit("Resident totals do not reconcile")
    if sum(point["jobs"] for point in points.values()) != job_total:
        raise SystemExit("Job totals do not reconcile")
    print(f"Validated AMBA: {len(points)} points, {len(demand['pops'])} populations")


if __name__ == "__main__":
    main()
