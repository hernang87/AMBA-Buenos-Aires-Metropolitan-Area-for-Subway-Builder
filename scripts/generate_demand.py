from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __package__:
    from .demand.clustering import (
        aggregate_workplaces_to_clusters,
        allocate_cluster_counts,
        build_adaptive_clusters,
        build_destination_zones,
    )
    from .demand.common import (
        EARTH_KM_PER_DEGREE,
        distance_km,
        integerize,
        representative_point,
        weighted_percentile,
    )
    from .demand.inputs import load_anchors, load_census_radios, load_workplaces
    from .demand.output import (
        add_population,
        build_demand_report,
        build_output_demand,
        register_point,
    )
    from .demand.pipeline import run_pipeline
    from .demand.transport import (
        allocate_cell_flows,
        balance_flows,
        build_candidate_edges,
        disaggregate_zone_flows,
        solve_sparse_transport,
    )
else:
    from demand.clustering import (
        aggregate_workplaces_to_clusters,
        allocate_cluster_counts,
        build_adaptive_clusters,
        build_destination_zones,
    )
    from demand.common import (
        EARTH_KM_PER_DEGREE,
        distance_km,
        integerize,
        representative_point,
        weighted_percentile,
    )
    from demand.inputs import load_anchors, load_census_radios, load_workplaces
    from demand.output import (
        add_population,
        build_demand_report,
        build_output_demand,
        register_point,
    )
    from demand.pipeline import run_pipeline
    from demand.transport import (
        allocate_cell_flows,
        balance_flows,
        build_candidate_edges,
        disaggregate_zone_flows,
        solve_sparse_transport,
    )

__all__ = [
    "EARTH_KM_PER_DEGREE",
    "ROOT",
    "add_population",
    "aggregate_workplaces_to_clusters",
    "allocate_cell_flows",
    "allocate_cluster_counts",
    "balance_flows",
    "build_adaptive_clusters",
    "build_candidate_edges",
    "build_demand_report",
    "build_destination_zones",
    "build_output_demand",
    "disaggregate_zone_flows",
    "distance_km",
    "integerize",
    "load_anchors",
    "load_census_radios",
    "load_workplaces",
    "main",
    "register_point",
    "representative_point",
    "run_pipeline",
    "solve_sparse_transport",
    "weighted_percentile",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--areas", type=Path, default=ROOT / "data/processed/areas.csv")
    parser.add_argument("--workplaces", type=Path, default=ROOT / "data/processed/workplaces.csv")
    parser.add_argument("--anchors", type=Path, default=ROOT / "data/processed/caba_anchors.csv")
    parser.add_argument("--config", type=Path, default=ROOT / "config/bue.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/BUE/demand_data.json")
    args = parser.parse_args()

    run_pipeline(args.areas, args.workplaces, args.anchors, args.config, args.output)


if __name__ == "__main__":
    main()
