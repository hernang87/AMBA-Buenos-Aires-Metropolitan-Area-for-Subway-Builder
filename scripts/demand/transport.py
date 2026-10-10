from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import maximum_flow

from .common import EARTH_KM_PER_DEGREE, distance_km


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
