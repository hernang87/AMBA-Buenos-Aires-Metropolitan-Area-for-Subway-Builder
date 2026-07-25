from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import maximum_flow
from scipy.spatial import cKDTree
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


def aggregate_workplaces_to_origins(
    workplaces: list[dict[str, object]],
    origins: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Place rounded workplace capacity on the nearest census-derived demand zone."""
    if not origins:
        raise ValueError("Cannot aggregate workplaces without census-derived origins")
    mean_latitude = math.radians(
        sum(float(origin["location"][1]) for origin in origins) / len(origins)
    )
    longitude_scale = math.cos(mean_latitude)
    origin_locations = np.array(
        [
            (float(origin["location"][0]) * longitude_scale, float(origin["location"][1]))
            for origin in origins
        ],
        dtype=float,
    )
    workplace_locations = np.array(
        [
            (float(workplace["location"][0]) * longitude_scale, float(workplace["location"][1]))
            for workplace in workplaces
        ],
        dtype=float,
    )
    _, nearest_origins = cKDTree(origin_locations).query(workplace_locations, k=1)
    capacities = np.bincount(
        nearest_origins,
        weights=np.array([int(workplace["capacity"]) for workplace in workplaces], dtype=np.int64),
        minlength=len(origins),
    ).astype(np.int64)
    return [
        {
            "id": f"workplace_{origin['id']}",
            "cell_id": f"workplace_{origin['id']}",
            "location": tuple(origin["location"]),
            "capacity": int(capacity),
        }
        for origin, capacity in zip(origins, capacities)
        if capacity > 0
    ]


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


def solve_sparse_transport(
    origin_targets: np.ndarray,
    cell_targets: np.ndarray,
    origin_indices: np.ndarray,
    cell_indices: np.ndarray,
    gravity_flows: np.ndarray,
    capacity_multiplier: float = 16.0,
) -> np.ndarray:
    """Project a dense gravity matrix onto an exact sparse transportation vertex."""
    if int(origin_targets.sum()) != int(cell_targets.sum()):
        raise ValueError("Sparse gravity projection marginals do not reconcile")
    if len(origin_indices) != len(cell_indices) or len(origin_indices) != len(gravity_flows):
        raise ValueError("Sparse gravity projection edge arrays do not reconcile")

    if capacity_multiplier < 1:
        raise ValueError("Sparse projection capacity multiplier must be at least 1")

    origin_count = len(origin_targets)
    cell_count = len(cell_targets)
    sink = 1 + origin_count + cell_count
    edge_capacities = np.ceil(gravity_flows * capacity_multiplier).astype(np.int64)
    graph_rows = np.concatenate(
        (
            np.zeros(origin_count, dtype=np.int64),
            1 + origin_indices,
            1 + origin_count + np.arange(cell_count, dtype=np.int64),
        )
    )
    graph_columns = np.concatenate(
        (
            1 + np.arange(origin_count, dtype=np.int64),
            1 + origin_count + cell_indices,
            np.full(cell_count, sink, dtype=np.int64),
        )
    )
    graph_capacities = np.concatenate((origin_targets, edge_capacities, cell_targets))
    capacity_graph = coo_matrix(
        (graph_capacities, (graph_rows, graph_columns)),
        shape=(sink + 1, sink + 1),
    ).tocsr()
    feasible = maximum_flow(capacity_graph, 0, sink)
    if int(feasible.flow_value) != int(origin_targets.sum()):
        raise ValueError(
            "Sparse gravity projection failed: gravity-bounded support cannot carry all formal jobs"
        )

    flow_block = feasible.flow[1 : 1 + origin_count, 1 + origin_count : sink].tocoo()
    positive = flow_block.data > 0
    support_rows = flow_block.row[positive]
    support_cells = flow_block.col[positive]
    edge_lookup = coo_matrix(
        (
            np.arange(len(gravity_flows), dtype=np.int64) + 1,
            (origin_indices, cell_indices),
        ),
        shape=(origin_count, cell_count),
    ).tocsr()
    support_edges = np.asarray(edge_lookup[support_rows, support_cells]).ravel().astype(np.int64) - 1
    if np.any(support_edges < 0):
        raise ValueError("Sparse gravity projection produced an unknown support edge")

    support_origins = origin_indices[support_edges]
    support_cell_indices = cell_indices[support_edges]
    support_gravity = gravity_flows[support_edges]
    support_indices = np.arange(len(support_edges), dtype=np.int64)
    constraint_rows = np.concatenate((support_origins, origin_count + support_cell_indices))
    constraint_columns = np.concatenate((support_indices, support_indices))
    constraints = coo_matrix(
        (np.ones(len(support_indices) * 2), (constraint_rows, constraint_columns)),
        shape=(origin_count + cell_count, len(support_indices)),
    ).tocsr()
    margins = np.concatenate((origin_targets, cell_targets)).astype(float)

    probabilities = support_gravity / origin_targets[support_origins]
    costs = -np.log(np.maximum(probabilities, np.finfo(float).tiny))
    costs += support_indices * np.finfo(float).eps
    result = linprog(
        costs,
        A_eq=constraints,
        b_eq=margins,
        bounds=(0, None),
        method="highs-ds",
    )
    if not result.success or result.x is None:
        message = result.message if result.message else "unknown solver error"
        raise ValueError(f"Sparse gravity projection failed: {message}")

    rounded = np.rint(result.x)
    if float(np.max(np.abs(result.x - rounded), initial=0.0)) > 1e-5:
        raise ValueError("Sparse gravity projection returned non-integral flows")
    sparse_flows = np.zeros(len(gravity_flows), dtype=np.int64)
    sparse_flows[support_edges] = rounded.astype(np.int64)
    assigned_origins = np.bincount(origin_indices, weights=sparse_flows, minlength=len(origin_targets)).astype(np.int64)
    assigned_cells = np.bincount(cell_indices, weights=sparse_flows, minlength=len(cell_targets)).astype(np.int64)
    if not np.array_equal(assigned_origins, origin_targets) or not np.array_equal(assigned_cells, cell_targets):
        raise ValueError("Sparse gravity projection did not preserve exact marginals")
    return sparse_flows


def allocate_cell_flows(
    origin_flows: list[tuple[int, int]],
    workplace_capacities: list[tuple[int, int]],
) -> list[tuple[int, int, int]]:
    """Allocate cell-level flows to native workplaces with a sparse two-pointer pass."""
    if sum(size for _, size in origin_flows) != sum(size for _, size in workplace_capacities):
        raise ValueError("Cell origin flows and workplace capacities do not reconcile")

    origins = [[index, size] for index, size in sorted(origin_flows, key=lambda item: (-item[1], item[0])) if size]
    workplaces = [
        [index, size]
        for index, size in sorted(workplace_capacities, key=lambda item: (-item[1], item[0]))
        if size
    ]
    assignments: list[tuple[int, int, int]] = []
    origin_index = 0
    workplace_index = 0
    while origin_index < len(origins) and workplace_index < len(workplaces):
        size = min(origins[origin_index][1], workplaces[workplace_index][1])
        assignments.append((origins[origin_index][0], workplaces[workplace_index][0], size))
        origins[origin_index][1] -= size
        workplaces[workplace_index][1] -= size
        if not origins[origin_index][1]:
            origin_index += 1
        if not workplaces[workplace_index][1]:
            workplace_index += 1
    if origin_index != len(origins) or workplace_index != len(workplaces):
        raise ValueError("Cell allocation ended with unassigned demand")
    return assignments


def register_point(
    points: list[dict[str, object]],
    points_by_location: dict[tuple[float, float], dict[str, object]],
    point_id: str,
    location: tuple[float, float],
) -> dict[str, object]:
    point = points_by_location.get(location)
    if point is not None:
        return point
    point = {"id": point_id, "location": list(location), "jobs": 0, "residents": 0, "popIds": []}
    points.append(point)
    points_by_location[location] = point
    return point


def add_population(
    pops: list[dict[str, object]],
    residence: dict[str, object],
    destination: dict[str, object],
    size: int,
    distance: float,
    pop_index: int,
) -> int:
    pop_id = f"pop_{pop_index:08d}"
    pop = {
        "residenceId": residence["id"],
        "jobId": destination["id"],
        "drivingSeconds": round(distance / 35 * 3600),
        "drivingDistance": round(distance * 1000),
        "size": size,
        "id": pop_id,
    }
    pops.append(pop)
    residence["residents"] += size
    residence["popIds"].append(pop_id)
    destination["jobs"] += size
    if destination is not residence:
        destination["popIds"].append(pop_id)
    return pop_index + 1


def build_output_demand(
    origins: list[dict[str, object]],
    workplaces: list[dict[str, object]],
    formal_assignments: list[tuple[int, int, int]],
    residual_targets: np.ndarray,
    maximum_population_size: int,
) -> dict[str, list[dict[str, object]]]:
    if maximum_population_size <= 0:
        raise ValueError("maximum_population_size must be positive")
    if len(residual_targets) != len(origins):
        raise ValueError("Residual origin targets do not reconcile")

    points: list[dict[str, object]] = []
    points_by_location: dict[tuple[float, float], dict[str, object]] = {}
    origin_points = [
        register_point(points, points_by_location, str(origin["id"]), tuple(origin["location"]))
        for origin in origins
    ]
    workplace_points = [
        register_point(points, points_by_location, str(workplace["id"]), tuple(workplace["location"]))
        for workplace in workplaces
    ]
    pops: list[dict[str, object]] = []
    pop_index = 0

    for origin_index, workplace_index, assignment_size in formal_assignments:
        residence = origin_points[origin_index]
        destination = workplace_points[workplace_index]
        distance = distance_km(tuple(residence["location"]), tuple(destination["location"]))
        remaining = assignment_size
        while remaining:
            chunk = min(remaining, maximum_population_size)
            pop_index = add_population(pops, residence, destination, chunk, distance, pop_index)
            remaining -= chunk

    for origin_index, residual in enumerate(residual_targets):
        residence = origin_points[origin_index]
        remaining = int(residual)
        while remaining:
            chunk = min(remaining, maximum_population_size)
            pop_index = add_population(pops, residence, residence, chunk, 0.0, pop_index)
            remaining -= chunk

    return {
        "points": [point for point in points if point["residents"] or point["jobs"]],
        "pops": pops,
    }


def weighted_percentile(values: np.ndarray, weights: np.ndarray, percentile: float) -> float:
    if not len(values) or int(weights.sum()) == 0:
        return 0.0
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    position = np.searchsorted(cumulative, weights.sum() * percentile, side="left")
    return float(values[order[min(position, len(order) - 1)]])


def build_demand_report(
    demand: dict[str, list[dict[str, object]]],
    dense_flows: np.ndarray,
    sparse_flows: np.ndarray,
    origin_indices: np.ndarray,
    cell_indices: np.ndarray,
    origins: list[dict[str, object]],
    cells: list[dict[str, object]],
    employed_total: int,
    formal_total: int,
) -> dict[str, object]:
    dense_distances = np.array(
        [distance_km(origins[int(i)]["location"], cells[int(j)]["location"]) for i, j in zip(origin_indices, cell_indices)]
    )
    formal_distances = np.array([pop["drivingDistance"] / 1000 for pop in demand["pops"] if pop["drivingDistance"]])
    formal_sizes = np.array([pop["size"] for pop in demand["pops"] if pop["drivingDistance"]], dtype=np.int64)
    population_sizes = np.array([pop["size"] for pop in demand["pops"]], dtype=np.int64)
    dense_mean = float(np.dot(dense_distances, dense_flows) / formal_total)
    formal_mean = float(np.dot(formal_distances, formal_sizes) / formal_sizes.sum()) if len(formal_sizes) else 0.0
    return {
        "totals": {
            "employed": employed_total,
            "formal": formal_total,
            "local_residual": employed_total - formal_total,
        },
        "model": {
            "dense_candidate_edges": len(dense_flows),
            "dense_positive_edges": int(np.count_nonzero(dense_flows)),
            "sparse_cell_flows": int(np.count_nonzero(sparse_flows)),
            "dense_formal_mean_km": dense_mean,
            "dense_formal_p90_km": weighted_percentile(dense_distances, dense_flows, 0.9),
            "sparse_formal_mean_km": formal_mean,
            "sparse_formal_p50_km": weighted_percentile(formal_distances, formal_sizes, 0.5),
            "sparse_formal_p90_km": weighted_percentile(formal_distances, formal_sizes, 0.9),
            "sparse_formal_max_km": float(formal_distances.max(initial=0.0)),
        },
        "output": {
            "points": len(demand["points"]),
            "job_points": sum(bool(point["jobs"]) for point in demand["points"]),
            "resident_points": sum(bool(point["residents"]) for point in demand["points"]),
            "duplicate_coordinates": len(demand["points"])
            - len({tuple(point["location"]) for point in demand["points"]}),
            "populations": len(demand["pops"]),
            "population_size_min": int(population_sizes.min()) if len(population_sizes) else 0,
            "population_size_median": float(np.median(population_sizes)),
            "population_size_mean": float(population_sizes.mean()),
            "population_size_p90": float(np.percentile(population_sizes, 90)),
            "population_size_max": int(population_sizes.max(initial=0)),
        },
    }


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
    maximum_population_size = int(demand_config["maximum_population_size"])
    maximum_population_count = int(demand_config["maximum_population_count"])
    projection_capacity_multiplier = float(demand_config["projection_capacity_multiplier"])
    tolerance = float(demand_config["ipf_tolerance"])
    max_iterations = int(demand_config["ipf_max_iterations"])
    origins = load_origins(args.areas, float(demand_config["origin_grid_degrees"]), config["bbox"])
    native_workplaces = load_workplaces(args.workplaces)
    workplaces = aggregate_workplaces_to_origins(native_workplaces, origins)
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
    sparse_flows = solve_sparse_transport(
        formal_origin_targets,
        cell_targets,
        origin_indices,
        cell_indices,
        balanced,
        projection_capacity_multiplier,
    )
    employed_targets = np.array([int(round(float(origin["employed_residents"]))) for origin in origins], dtype=np.int64)
    residual_targets = employed_targets - formal_origin_targets
    if np.any(residual_targets < 0) or int(residual_targets.sum()) != employed_total - formal_total:
        raise ValueError("Could not reconcile local residual employment")

    edges_by_cell: dict[int, list[int]] = defaultdict(list)
    for edge_index, flow in enumerate(sparse_flows):
        if flow:
            edges_by_cell[int(cell_indices[edge_index])].append(edge_index)

    formal_assignments: list[tuple[int, int, int]] = []
    for cell_index, edge_indices in edges_by_cell.items():
        workplace_indices = workplaces_by_cell[str(cells[cell_index]["id"])]
        formal_assignments.extend(
            allocate_cell_flows(
                [(int(origin_indices[edge_index]), int(sparse_flows[edge_index])) for edge_index in edge_indices],
                [(workplace_index, int(workplaces[workplace_index]["capacity"])) for workplace_index in workplace_indices],
            )
        )

    demand = build_output_demand(
        origins,
        workplaces,
        formal_assignments,
        residual_targets,
        maximum_population_size,
    )
    if len(demand["pops"]) > maximum_population_count:
        raise ValueError(
            f"Population count exceeds {maximum_population_count}: {len(demand['pops'])}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(demand, separators=(",", ":")), encoding="utf-8")
    config_path = args.output.parent / "config.json"
    if config_path.exists():
        output_config = json.loads(config_path.read_text(encoding="utf-8"))
        output_config["population"] = sum(pop["size"] for pop in demand["pops"])
        output_config["version"] = config["version"]
        config_path.write_text(json.dumps(output_config, indent=2) + "\n", encoding="utf-8")
    report = build_demand_report(
        demand,
        balanced,
        sparse_flows,
        origin_indices,
        cell_indices,
        origins,
        cells,
        employed_total,
        formal_total,
    )
    report["output"]["demand_json_bytes"] = args.output.stat().st_size
    (args.output.parent / "demand_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Generated {len(demand['points'])} census-derived points and {len(demand['pops'])} populations; "
        f"formal jobs {formal_total}, local residual {employed_total - formal_total}"
    )


if __name__ == "__main__":
    main()
