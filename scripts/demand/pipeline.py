from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .clustering import (
    aggregate_workplaces_to_clusters,
    build_adaptive_clusters,
    build_destination_zones,
)
from .common import integerize
from .inputs import load_anchors, load_census_radios, load_workplaces
from .output import build_demand_report, build_output_demand
from .transport import (
    balance_flows,
    build_candidate_edges,
    disaggregate_zone_flows,
    solve_sparse_transport,
)


def run_pipeline(
    areas_path: Path,
    workplaces_path: Path,
    anchors_path: Path,
    config_path: Path,
    output_path: Path,
) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
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
    anchors = load_anchors(anchors_path)
    radios = load_census_radios(areas_path, float(demand_config["solver_zone_degrees"]), anchors)
    display_clusters, solver_zones = build_adaptive_clusters(
        radios,
        display_cluster_count,
        config["bbox"],
    )
    native_workplaces = load_workplaces(workplaces_path)
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(demand, separators=(",", ":")), encoding="utf-8")
    config_path = output_path.parent / "config.json"
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
    report["output"]["demand_json_bytes"] = output_path.stat().st_size
    report["output"]["caba_anchored_radios"] = len(anchors)
    (output_path.parent / "demand_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Generated {len(demand['points'])} adaptive census points and {len(demand['pops'])} populations; "
        f"formal jobs {formal_total}, local residual {employed_total - formal_total}"
    )
