from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import cut_tree, linkage
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


def load_census_radios(path: Path, solver_zone_degrees: float) -> list[dict[str, object]]:
    radios: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            location = representative_point(json.loads(row["geometry"]))
            radios.append(
                {
                    "id": row["area_id"],
                    "location": location,
                    "employed_residents": int(round(float(row["jobs"]))),
                    "zone_key": (
                        math.floor(location[0] / solver_zone_degrees),
                        math.floor(location[1] / solver_zone_degrees),
                    ),
                }
            )
    if not radios:
        raise ValueError("No prepared census areas found")
    return radios


def allocate_cluster_counts(
    zone_employment: list[int],
    zone_radio_counts: list[int],
    display_cluster_count: int,
) -> list[int]:
    zone_count = len(zone_employment)
    total_radios = sum(zone_radio_counts)
    if display_cluster_count < zone_count or display_cluster_count > total_radios:
        raise ValueError(
            f"display_cluster_count must be between solver-zone count {zone_count} "
            f"and census-radio count {total_radios}"
        )
    counts = [1] * zone_count
    priorities: list[tuple[float, int]] = []
    for zone_index, (employment, radio_count) in enumerate(zip(zone_employment, zone_radio_counts)):
        if radio_count > 1:
            heapq.heappush(priorities, (-employment / 2, zone_index))
    for _ in range(display_cluster_count - zone_count):
        if not priorities:
            raise ValueError("Could not allocate the requested display clusters")
        _, zone_index = heapq.heappop(priorities)
        counts[zone_index] += 1
        if counts[zone_index] < zone_radio_counts[zone_index]:
            heapq.heappush(
                priorities,
                (-zone_employment[zone_index] / (counts[zone_index] + 1), zone_index),
            )
    return counts


def build_adaptive_clusters(
    radios: list[dict[str, object]],
    display_cluster_count: int,
    bbox: list[float] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    radio_indices_by_zone: dict[tuple[int, int], list[int]] = defaultdict(list)
    for radio_index, radio in enumerate(radios):
        radio_indices_by_zone[tuple(radio["zone_key"])].append(radio_index)
    zone_keys = sorted(radio_indices_by_zone)
    zone_employment = [
        sum(int(radios[index]["employed_residents"]) for index in radio_indices_by_zone[key])
        for key in zone_keys
    ]
    cluster_counts = allocate_cluster_counts(
        zone_employment,
        [len(radio_indices_by_zone[key]) for key in zone_keys],
        display_cluster_count,
    )
    mean_latitude = math.radians(
        sum(float(radio["location"][1]) for radio in radios) / len(radios)
    )
    longitude_scale = math.cos(mean_latitude)
    clusters: list[dict[str, object]] = []
    solver_zones: list[dict[str, object]] = []
    for zone_index, (zone_key, cluster_count) in enumerate(zip(zone_keys, cluster_counts)):
        radio_indices = radio_indices_by_zone[zone_key]
        coordinates = np.array(
            [
                (
                    float(radios[index]["location"][0]) * longitude_scale,
                    float(radios[index]["location"][1]),
                )
                for index in radio_indices
            ],
            dtype=float,
        )
        labels = (
            np.zeros(len(radio_indices), dtype=np.int64)
            if cluster_count == 1
            else cut_tree(linkage(coordinates, method="ward"), n_clusters=[cluster_count]).ravel()
        )
        zone_cluster_indices: list[int] = []
        for label in range(cluster_count):
            member_indices = [
                radio_index
                for radio_index, member_label in zip(radio_indices, labels)
                if int(member_label) == label
            ]
            weights = np.array(
                [max(int(radios[index]["employed_residents"]), 1) for index in member_indices],
                dtype=float,
            )
            member_locations = np.array([radios[index]["location"] for index in member_indices], dtype=float)
            cluster_index = len(clusters)
            longitude, latitude = np.average(member_locations, axis=0, weights=weights)
            if bbox is not None:
                west, south, east, north = bbox
                longitude = min(max(float(longitude), west), east)
                latitude = min(max(float(latitude), south), north)
            cluster = {
                "id": f"origin_{cluster_index:05d}",
                "location": (float(longitude), float(latitude)),
                "employed_residents": sum(int(radios[index]["employed_residents"]) for index in member_indices),
                "radio_count": len(member_indices),
                "zone_index": zone_index,
            }
            clusters.append(cluster)
            zone_cluster_indices.append(cluster_index)
            for radio_index in member_indices:
                radios[radio_index]["cluster_index"] = cluster_index
        zone_weights = np.array(
            [max(int(clusters[index]["employed_residents"]), 1) for index in zone_cluster_indices],
            dtype=float,
        )
        zone_locations = np.array([clusters[index]["location"] for index in zone_cluster_indices], dtype=float)
        solver_zones.append(
            {
                "id": f"zone_{zone_key[0]}_{zone_key[1]}",
                "location": tuple(np.average(zone_locations, axis=0, weights=zone_weights)),
                "employed_residents": zone_employment[zone_index],
                "cluster_indices": zone_cluster_indices,
            }
        )
    if len(clusters) != display_cluster_count:
        raise ValueError("Adaptive clustering did not produce the requested point count")
    if len({tuple(cluster["location"]) for cluster in clusters}) != len(clusters):
        raise ValueError("Adaptive clustering produced duplicate coordinates")
    return clusters, solver_zones


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


def aggregate_workplaces_to_clusters(
    workplaces: list[dict[str, object]],
    radios: list[dict[str, object]],
    clusters: list[dict[str, object]],
) -> np.ndarray:
    """Assign rounded workplace capacity through the nearest census radio."""
    if not radios or not clusters:
        raise ValueError("Cannot aggregate workplaces without census radios and display clusters")
    mean_latitude = math.radians(
        sum(float(radio["location"][1]) for radio in radios) / len(radios)
    )
    longitude_scale = math.cos(mean_latitude)
    radio_locations = np.array(
        [
            (float(radio["location"][0]) * longitude_scale, float(radio["location"][1]))
            for radio in radios
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
    _, nearest_radios = cKDTree(radio_locations).query(workplace_locations, k=1)
    nearest_clusters = np.array(
        [int(radios[int(radio_index)]["cluster_index"]) for radio_index in nearest_radios],
        dtype=np.int64,
    )
    return np.bincount(
        nearest_clusters,
        weights=np.array([int(workplace["capacity"]) for workplace in workplaces], dtype=np.int64),
        minlength=len(clusters),
    ).astype(np.int64)


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
    flow_quantum: int = 10,
) -> np.ndarray:
    """Project a dense gravity matrix onto an exact sparse transportation vertex."""
    if int(origin_targets.sum()) != int(cell_targets.sum()):
        raise ValueError("Sparse gravity projection marginals do not reconcile")
    if len(origin_indices) != len(cell_indices) or len(origin_indices) != len(gravity_flows):
        raise ValueError("Sparse gravity projection edge arrays do not reconcile")

    if capacity_multiplier < 1:
        raise ValueError("Sparse projection capacity multiplier must be at least 1")
    if flow_quantum < 1:
        raise ValueError("Sparse projection flow quantum must be at least 1")

    origin_count = len(origin_targets)
    cell_count = len(cell_targets)
    sink = 1 + origin_count + cell_count
    lower_flows = (np.floor(gravity_flows / flow_quantum) * flow_quantum).astype(np.int64)
    lower_origin_totals = np.bincount(origin_indices, weights=lower_flows, minlength=origin_count).astype(np.int64)
    lower_cell_totals = np.bincount(cell_indices, weights=lower_flows, minlength=cell_count).astype(np.int64)
    residual_origin_targets = origin_targets - lower_origin_totals
    residual_cell_targets = cell_targets - lower_cell_totals
    if np.any(residual_origin_targets < 0) or np.any(residual_cell_targets < 0):
        raise ValueError("Sparse projection lower flows exceed a marginal")
    if int(residual_origin_targets.sum()) == 0:
        return lower_flows
    edge_capacities = (
        np.ceil(gravity_flows * capacity_multiplier).astype(np.int64) - lower_flows
    )
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
    graph_capacities = np.concatenate(
        (residual_origin_targets, edge_capacities, residual_cell_targets)
    )
    capacity_graph = coo_matrix(
        (graph_capacities, (graph_rows, graph_columns)),
        shape=(sink + 1, sink + 1),
    ).tocsr()
    feasible = maximum_flow(capacity_graph, 0, sink)
    if int(feasible.flow_value) != int(residual_origin_targets.sum()):
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
    margins = np.concatenate((residual_origin_targets, residual_cell_targets)).astype(float)

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
    sparse_flows = lower_flows.copy()
    sparse_flows[support_edges] += rounded.astype(np.int64)
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


def build_destination_zones(
    solver_zones: list[dict[str, object]],
    cluster_capacities: np.ndarray,
) -> tuple[list[dict[str, object]], dict[int, int]]:
    destinations: list[dict[str, object]] = []
    destination_index_by_zone: dict[int, int] = {}
    for zone_index, zone in enumerate(solver_zones):
        capacity = int(sum(cluster_capacities[index] for index in zone["cluster_indices"]))
        if not capacity:
            continue
        destination_index_by_zone[zone_index] = len(destinations)
        destinations.append(
            {
                "id": f"destination_{zone['id']}",
                "location": tuple(zone["location"]),
                "capacity": capacity,
                "zone_index": zone_index,
            }
        )
    return destinations, destination_index_by_zone


def disaggregate_zone_flows(
    sparse_flows: np.ndarray,
    origin_indices: np.ndarray,
    destination_indices: np.ndarray,
    solver_zones: list[dict[str, object]],
    destination_zones: list[dict[str, object]],
    cluster_origin_targets: np.ndarray,
    cluster_capacities: np.ndarray,
) -> list[tuple[int, int, int]]:
    outgoing_by_zone: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for edge_index in np.flatnonzero(sparse_flows):
        outgoing_by_zone[int(origin_indices[edge_index])].append(
            (int(destination_indices[edge_index]), int(sparse_flows[edge_index]))
        )

    incoming_segments: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for zone_index, outgoing in outgoing_by_zone.items():
        origin_clusters = [
            (int(cluster_index), int(cluster_origin_targets[cluster_index]))
            for cluster_index in solver_zones[zone_index]["cluster_indices"]
            if cluster_origin_targets[cluster_index]
        ]
        for cluster_index, destination_index, size in allocate_cell_flows(origin_clusters, outgoing):
            incoming_segments[destination_index].append((cluster_index, size))

    assignments: list[tuple[int, int, int]] = []
    for destination_index, segments in incoming_segments.items():
        zone_index = int(destination_zones[destination_index]["zone_index"])
        destination_clusters = [
            (int(cluster_index), int(cluster_capacities[cluster_index]))
            for cluster_index in solver_zones[zone_index]["cluster_indices"]
            if cluster_capacities[cluster_index]
        ]
        assignments.extend(allocate_cell_flows(segments, destination_clusters))

    assigned_origins = np.bincount(
        [origin for origin, _, _ in assignments],
        weights=[size for _, _, size in assignments],
        minlength=len(cluster_origin_targets),
    ).astype(np.int64)
    assigned_destinations = np.bincount(
        [destination for _, destination, _ in assignments],
        weights=[size for _, _, size in assignments],
        minlength=len(cluster_capacities),
    ).astype(np.int64)
    if not np.array_equal(assigned_origins, cluster_origin_targets):
        raise ValueError("Disaggregated origin-cluster totals do not reconcile")
    if not np.array_equal(assigned_destinations, cluster_capacities):
        raise ValueError("Disaggregated destination-cluster totals do not reconcile")
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
    solver_origins: list[dict[str, object]],
    destination_zones: list[dict[str, object]],
    display_clusters: list[dict[str, object]],
    formal_assignments: list[tuple[int, int, int]],
    employed_total: int,
    formal_total: int,
) -> dict[str, object]:
    dense_distances = np.array(
        [
            distance_km(
                solver_origins[int(i)]["location"],
                destination_zones[int(j)]["location"],
            )
            for i, j in zip(origin_indices, cell_indices)
        ]
    )
    formal_distances = np.array(
        [
            distance_km(
                display_clusters[origin_index]["location"],
                display_clusters[destination_index]["location"],
            )
            for origin_index, destination_index, _ in formal_assignments
        ]
    )
    formal_sizes = np.array([size for _, _, size in formal_assignments], dtype=np.int64)
    population_sizes = np.array([pop["size"] for pop in demand["pops"]], dtype=np.int64)
    radio_counts = np.array([int(cluster["radio_count"]) for cluster in display_clusters], dtype=np.int64)
    cluster_employment = np.array(
        [int(cluster["employed_residents"]) for cluster in display_clusters],
        dtype=np.int64,
    )
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
            "solver_zones": len(solver_origins),
            "sparse_zone_flows": int(np.count_nonzero(sparse_flows)),
            "dense_formal_mean_km": dense_mean,
            "dense_formal_p90_km": weighted_percentile(dense_distances, dense_flows, 0.9),
            "exported_formal_mean_km": formal_mean,
            "exported_formal_p50_km": weighted_percentile(formal_distances, formal_sizes, 0.5),
            "exported_formal_p90_km": weighted_percentile(formal_distances, formal_sizes, 0.9),
            "exported_formal_max_km": float(formal_distances.max(initial=0.0)),
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
            "radios_per_cluster_median": float(np.median(radio_counts)),
            "radios_per_cluster_p90": float(np.percentile(radio_counts, 90)),
            "radios_per_cluster_max": int(radio_counts.max(initial=0)),
            "employed_per_cluster_median": float(np.median(cluster_employment)),
            "employed_per_cluster_p90": float(np.percentile(cluster_employment, 90)),
            "employed_per_cluster_max": int(cluster_employment.max(initial=0)),
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
    projection_flow_quantum = int(demand_config["projection_flow_quantum"])
    tolerance = float(demand_config["ipf_tolerance"])
    max_iterations = int(demand_config["ipf_max_iterations"])
    display_cluster_count = int(demand_config["display_cluster_count"])
    radios = load_census_radios(args.areas, float(demand_config["solver_zone_degrees"]))
    display_clusters, solver_zones = build_adaptive_clusters(
        radios,
        display_cluster_count,
        config["bbox"],
    )
    native_workplaces = load_workplaces(args.workplaces)
    cluster_capacities = aggregate_workplaces_to_clusters(native_workplaces, radios, display_clusters)
    destination_zones, _ = build_destination_zones(solver_zones, cluster_capacities)

    employed_targets = np.array(
        [int(cluster["employed_residents"]) for cluster in display_clusters],
        dtype=np.int64,
    )
    employed_total = int(employed_targets.sum())
    formal_total = min(employed_total, int(cluster_capacities.sum()))
    cluster_formal_targets = integerize(
        employed_targets.astype(float) * formal_total / employed_total,
        formal_total,
    )
    solver_origin_targets = np.bincount(
        [int(cluster["zone_index"]) for cluster in display_clusters],
        weights=cluster_formal_targets,
        minlength=len(solver_zones),
    ).astype(np.int64)
    destination_targets = np.array(
        [int(destination["capacity"]) for destination in destination_zones],
        dtype=np.int64,
    )
    origin_indices, destination_indices, base_weights = build_candidate_edges(
        solver_zones,
        destination_zones,
        decay,
        candidate_count,
    )
    balanced = balance_flows(
        solver_origin_targets,
        destination_targets,
        origin_indices,
        destination_indices,
        base_weights,
        tolerance,
        max_iterations,
    )
    sparse_flows = solve_sparse_transport(
        solver_origin_targets,
        destination_targets,
        origin_indices,
        destination_indices,
        balanced,
        projection_capacity_multiplier,
        projection_flow_quantum,
    )
    residual_targets = employed_targets - cluster_formal_targets
    if np.any(residual_targets < 0) or int(residual_targets.sum()) != employed_total - formal_total:
        raise ValueError("Could not reconcile local residual employment")

    formal_assignments = disaggregate_zone_flows(
        sparse_flows,
        origin_indices,
        destination_indices,
        solver_zones,
        destination_zones,
        cluster_formal_targets,
        cluster_capacities,
    )
    workplaces = [
        {
            "id": f"workplace_{cluster['id']}",
            "location": tuple(cluster["location"]),
            "capacity": int(cluster_capacities[index]),
        }
        for index, cluster in enumerate(display_clusters)
    ]

    demand = build_output_demand(
        display_clusters,
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
        destination_indices,
        solver_zones,
        destination_zones,
        display_clusters,
        formal_assignments,
        employed_total,
        formal_total,
    )
    report["output"]["demand_json_bytes"] = args.output.stat().st_size
    (args.output.parent / "demand_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Generated {len(demand['points'])} adaptive census points and {len(demand['pops'])} populations; "
        f"formal jobs {formal_total}, local residual {employed_total - formal_total}"
    )


if __name__ == "__main__":
    main()
