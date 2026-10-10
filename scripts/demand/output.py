from __future__ import annotations

import numpy as np

from .common import distance_km, weighted_percentile


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
