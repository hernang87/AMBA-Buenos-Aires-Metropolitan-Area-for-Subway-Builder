from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import shape


ROOT = Path(__file__).resolve().parents[1]
EARTH_KM_PER_DEGREE = 111.2


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


def integerize(values: np.ndarray, total: int | None = None) -> np.ndarray:
    floors = np.floor(values).astype(np.int64)
    target = int(round(float(values.sum()))) if total is None else total
    extra = target - int(floors.sum())
    if extra < 0 or extra > len(values):
        raise ValueError("Cannot integerize values with the requested total")
    if extra:
        fractions = values - floors
        indices = np.argpartition(fractions, -extra)[-extra:]
        floors[indices] += 1
    return floors


def load_origins(path: Path, grid_degrees: float, bbox: list[float]) -> list[dict[str, object]]:
    grouped: dict[tuple[int, int], dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            location = representative_point(json.loads(row["geometry"]))
            employed_residents = float(row["jobs"])
            key = (math.floor(location[0] / grid_degrees), math.floor(location[1] / grid_degrees))
            group = grouped.setdefault(
                key,
                {"employed_residents": 0.0, "weighted_lon": 0.0, "weighted_lat": 0.0, "weight": 0.0},
            )
            location_weight = max(employed_residents, 1.0)
            group["employed_residents"] += employed_residents
            group["weighted_lon"] += location[0] * location_weight
            group["weighted_lat"] += location[1] * location_weight
            group["weight"] += location_weight

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
            "employed_residents": group["employed_residents"],
        }
        for (grid_lon, grid_lat), group in sorted(grouped.items())
    ]


def load_workplaces(path: Path) -> list[dict[str, object]]:
    workplaces: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            workplaces.append(
                {
                    "id": row["workplace_id"],
                    "cell_id": row["cell_id"],
                    "location": (float(row["longitude"]), float(row["latitude"])),
                    "employment_weight": float(row["employment_weight"]),
                }
            )
    if not workplaces:
        raise ValueError("No prepared workplace establishments found")
    capacities = integerize(np.array([float(workplace["employment_weight"]) for workplace in workplaces]))
    for workplace, capacity in zip(workplaces, capacities):
        workplace["capacity"] = int(capacity)
    return workplaces


def build_cells(workplaces: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, list[int]]]:
    grouped: dict[str, dict[str, float]] = {}
    workplaces_by_cell: dict[str, list[int]] = defaultdict(list)
    for index, workplace in enumerate(workplaces):
        cell_id = str(workplace["cell_id"])
        location = workplace["location"]
        capacity = float(workplace["capacity"])
        group = grouped.setdefault(cell_id, {"capacity": 0.0, "weighted_lon": 0.0, "weighted_lat": 0.0})
        group["capacity"] += capacity
        group["weighted_lon"] += float(location[0]) * capacity
        group["weighted_lat"] += float(location[1]) * capacity
        workplaces_by_cell[cell_id].append(index)

    cells = []
    for cell_id, group in sorted(grouped.items()):
        capacity = int(round(group["capacity"]))
        cells.append(
            {
                "id": cell_id,
                "location": (group["weighted_lon"] / group["capacity"], group["weighted_lat"] / group["capacity"]),
                "capacity": capacity,
            }
        )
    return cells, workplaces_by_cell


def build_candidate_edges(
    origins: list[dict[str, object]],
    cells: list[dict[str, object]],
    decay: float,
    candidate_origins: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origin_locations = np.array([origin["location"] for origin in origins], dtype=float)
    cell_locations = np.array([cell["location"] for cell in cells], dtype=float)
    mean_latitude = math.radians(float(origin_locations[:, 1].mean()))
    longitude_scale = math.cos(mean_latitude)
    origin_indices: list[int] = []
    cell_indices: list[int] = []
    base_weights: list[float] = []
    covered_origins = np.zeros(len(origins), dtype=bool)
    count = min(candidate_origins, len(origins))
    for cell_index, (longitude, latitude) in enumerate(cell_locations):
        dx = (origin_locations[:, 0] - longitude) * longitude_scale * EARTH_KM_PER_DEGREE
        dy = (origin_locations[:, 1] - latitude) * EARTH_KM_PER_DEGREE
        nearest = np.argpartition(dx * dx + dy * dy, count - 1)[:count]
        for origin_index in nearest:
            distance = distance_km(
                (float(origin_locations[origin_index, 0]), float(origin_locations[origin_index, 1])),
                (float(longitude), float(latitude)),
            )
            origin_indices.append(int(origin_index))
            cell_indices.append(cell_index)
            base_weights.append(math.exp(-distance / decay))
            covered_origins[origin_index] = True
    for origin_index in np.flatnonzero(~covered_origins):
        dx = (cell_locations[:, 0] - origin_locations[origin_index, 0]) * longitude_scale * EARTH_KM_PER_DEGREE
        dy = (cell_locations[:, 1] - origin_locations[origin_index, 1]) * EARTH_KM_PER_DEGREE
        cell_index = int(np.argmin(dx * dx + dy * dy))
        distance = distance_km(
            (float(origin_locations[origin_index, 0]), float(origin_locations[origin_index, 1])),
            (float(cell_locations[cell_index, 0]), float(cell_locations[cell_index, 1])),
        )
        origin_indices.append(int(origin_index))
        cell_indices.append(cell_index)
        base_weights.append(math.exp(-distance / decay))
    origin_array = np.array(origin_indices, dtype=np.int64)
    cell_array = np.array(cell_indices, dtype=np.int64)
    base_array = np.array(base_weights, dtype=float)
    if len(np.unique(origin_array)) != len(origins):
        raise ValueError("Candidate workplace graph does not reach every origin")
    return origin_array, cell_array, base_array


def balance_flows(
    origin_targets: np.ndarray,
    cell_targets: np.ndarray,
    origin_indices: np.ndarray,
    cell_indices: np.ndarray,
    base_weights: np.ndarray,
    tolerance: float,
    max_iterations: int,
) -> np.ndarray:
    flows = base_weights.copy()
    for _ in range(max_iterations):
        origin_totals = np.bincount(origin_indices, weights=flows, minlength=len(origin_targets))
        if np.any(origin_totals <= 0):
            raise ValueError("A workplace candidate graph has an unreachable origin")
        flows *= origin_targets[origin_indices] / origin_totals[origin_indices]
        cell_totals = np.bincount(cell_indices, weights=flows, minlength=len(cell_targets))
        if np.any(cell_totals <= 0):
            raise ValueError("A workplace candidate graph has an unreachable destination cell")
        flows *= cell_targets[cell_indices] / cell_totals[cell_indices]
        origin_error = np.max(np.abs(np.bincount(origin_indices, weights=flows, minlength=len(origin_targets)) - origin_targets))
        cell_error = np.max(np.abs(np.bincount(cell_indices, weights=flows, minlength=len(cell_targets)) - cell_targets))
        if max(origin_error, cell_error) < tolerance:
            return flows
    raise ValueError("Gravity balancing did not converge")


def integerize_edges(
    flows: np.ndarray,
    cell_targets: np.ndarray,
    cell_indices: np.ndarray,
) -> np.ndarray:
    integer_flows = np.floor(flows).astype(np.int64)
    order = np.argsort(cell_indices)
    sorted_cells = cell_indices[order]
    boundaries = np.flatnonzero(np.r_[True, sorted_cells[1:] != sorted_cells[:-1], True])
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        edge_indices = order[start:end]
        integer_flows[edge_indices] = integerize(flows[edge_indices], int(cell_targets[sorted_cells[start]]))
    return integer_flows


def add_population(
    pops: list[dict[str, object]],
    points_by_id: dict[str, dict[str, object]],
    origin: dict[str, object],
    destination: dict[str, object],
    size: int,
    distance: float,
    pop_index: int,
) -> int:
    pop_id = f"pop_{pop_index:08d}"
    pop = {
        "residenceId": origin["id"],
        "jobId": destination["id"],
        "drivingSeconds": round(distance / 35 * 3600),
        "drivingDistance": round(distance * 1000),
        "size": size,
        "id": pop_id,
    }
    pops.append(pop)
    origin_point = points_by_id[origin["id"]]
    origin_point["residents"] += size
    origin_point["popIds"].append(pop_id)
    destination["jobs"] += size
    destination["popIds"].append(pop_id)
    return pop_index + 1


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
    candidate_count = int(demand_config["candidate_origins"])
    maximum_flow = int(demand_config["maximum_flow"])
    tolerance = float(demand_config["ipf_tolerance"])
    max_iterations = int(demand_config["ipf_max_iterations"])
    origins = load_origins(args.areas, float(demand_config["origin_grid_degrees"]), config["bbox"])
    workplaces = load_workplaces(args.workplaces)
    cells, workplaces_by_cell = build_cells(workplaces)

    employed_total = int(round(sum(float(origin["employed_residents"]) for origin in origins)))
    formal_total = min(employed_total, int(sum(int(workplace["capacity"]) for workplace in workplaces)))
    formal_origin_targets = integerize(
        np.array([float(origin["employed_residents"]) for origin in origins]) * formal_total / employed_total,
        formal_total,
    )
    cell_targets = np.array([int(cell["capacity"]) for cell in cells], dtype=np.int64)
    origin_indices, cell_indices, base_weights = build_candidate_edges(origins, cells, decay, candidate_count)
    balanced = balance_flows(
        formal_origin_targets,
        cell_targets,
        origin_indices,
        cell_indices,
        base_weights,
        tolerance,
        max_iterations,
    )
    integer_flows = integerize_edges(balanced, cell_targets, cell_indices)
    formal_assigned = np.bincount(origin_indices, weights=integer_flows, minlength=len(origins)).astype(np.int64)
    employed_targets = np.array([int(round(float(origin["employed_residents"]))) for origin in origins], dtype=np.int64)
    residual_targets = employed_targets - formal_assigned
    rounding_excess = int(-residual_targets[residual_targets < 0].sum())
    residual_targets[residual_targets < 0] = 0
    if rounding_excess:
        for origin_index in np.argsort(-residual_targets):
            if residual_targets[origin_index] <= 0:
                break
            adjustment = min(int(residual_targets[origin_index]), rounding_excess)
            residual_targets[origin_index] -= adjustment
            rounding_excess -= adjustment
            if not rounding_excess:
                break
    if np.any(residual_targets < 0) or int(residual_targets.sum()) != employed_total - formal_total:
        raise ValueError("Could not reconcile local residual employment after rounding")

    origin_points = [
        {"id": origin["id"], "location": list(origin["location"]), "jobs": 0, "residents": 0, "popIds": []}
        for origin in origins
    ]
    points_by_id = {point["id"]: point for point in origin_points}
    pops: list[dict[str, object]] = []
    pop_index = 0

    workplace_slots: dict[int, list[dict[str, object]]] = {}
    for workplace_index, workplace in enumerate(workplaces):
        slots = []
        remaining = int(workplace["capacity"])
        slot_index = 0
        while remaining:
            slot_size = min(maximum_flow, remaining)
            point = {
                "id": f"job_{workplace_index}_{slot_index}",
                "location": list(workplace["location"]),
                "jobs": 0,
                "residents": 0,
                "popIds": [],
            }
            points_by_id[point["id"]] = point
            slots.append({"point": point, "remaining": slot_size})
            remaining -= slot_size
            slot_index += 1
        workplace_slots[workplace_index] = slots

    edges_by_cell: dict[int, list[int]] = defaultdict(list)
    for edge_index, flow in enumerate(integer_flows):
        if flow:
            edges_by_cell[int(cell_indices[edge_index])].append(edge_index)

    for cell_index, edge_indices in edges_by_cell.items():
        workplace_indices = workplaces_by_cell[str(cells[cell_index]["id"])]
        workplace_index = 0
        slot_index = 0
        slots = workplace_slots[workplace_indices[workplace_index]]
        for edge_index in edge_indices:
            remaining_flow = int(integer_flows[edge_index])
            origin = origins[int(origin_indices[edge_index])]
            while remaining_flow:
                while not slots[slot_index]["remaining"]:
                    slot_index += 1
                    if slot_index == len(slots):
                        workplace_index += 1
                        if workplace_index == len(workplace_indices):
                            raise ValueError("Formal flow exceeds workplace capacity")
                        slots = workplace_slots[workplace_indices[workplace_index]]
                        slot_index = 0
                destination = slots[slot_index]["point"]
                chunk = min(remaining_flow, int(slots[slot_index]["remaining"]))
                distance = distance_km(origin["location"], destination["location"])
                pop_index = add_population(pops, points_by_id, origin, destination, chunk, distance, pop_index)
                slots[slot_index]["remaining"] -= chunk
                remaining_flow -= chunk

    for origin_index, origin in enumerate(origins):
        residual = int(residual_targets[origin_index])
        local_slot = 0
        while residual:
            chunk = min(maximum_flow, residual)
            point = {
                "id": f"local_{origin_index}_{local_slot}",
                "location": list(origin["location"]),
                "jobs": 0,
                "residents": 0,
                "popIds": [],
            }
            points_by_id[point["id"]] = point
            pop_index = add_population(pops, points_by_id, origin, point, chunk, 0.0, pop_index)
            residual -= chunk
            local_slot += 1

    points = [point for point in points_by_id.values() if point["residents"] or point["jobs"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"points": points, "pops": pops}, separators=(",", ":")), encoding="utf-8")
    config_path = args.output.parent / "config.json"
    if config_path.exists():
        output_config = json.loads(config_path.read_text(encoding="utf-8"))
        output_config["population"] = sum(pop["size"] for pop in pops)
        config_path.write_text(json.dumps(output_config, indent=2) + "\n", encoding="utf-8")
    residual_total = employed_total - formal_total
    print(
        f"Generated {len(points)} dispersed points and {len(pops)} populations; "
        f"formal jobs {formal_total}, local residual {residual_total}"
    )


if __name__ == "__main__":
    main()
