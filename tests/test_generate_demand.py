import unittest

import numpy as np

from scripts.generate_demand import (
    aggregate_workplaces_to_clusters,
    allocate_cluster_counts,
    allocate_cell_flows,
    build_adaptive_clusters,
    build_demand_report,
    build_output_demand,
    disaggregate_zone_flows,
    solve_sparse_transport,
)


class AdaptiveClusterTests(unittest.TestCase):
    def test_allocates_exact_cluster_budget_with_zone_bounds(self):
        self.assertEqual([2, 1, 2], allocate_cluster_counts([100, 10, 80], [2, 1, 3], 5))

    def test_rejects_cluster_budget_outside_zone_and_radio_bounds(self):
        with self.assertRaisesRegex(ValueError, "between solver-zone count"):
            allocate_cluster_counts([10, 20], [2, 2], 1)
        with self.assertRaisesRegex(ValueError, "between solver-zone count"):
            allocate_cluster_counts([10, 20], [2, 2], 5)

    def test_builds_deterministic_clusters_and_preserves_employment(self):
        radios = [
            {"id": "a", "location": (0.0, 0.0), "employed_residents": 10, "zone_key": (0, 0)},
            {"id": "b", "location": (0.1, 0.0), "employed_residents": 20, "zone_key": (0, 0)},
            {"id": "c", "location": (1.0, 1.0), "employed_residents": 30, "zone_key": (1, 1)},
        ]

        clusters, zones = build_adaptive_clusters(radios, 3)

        self.assertEqual(3, len(clusters))
        self.assertEqual(2, len(zones))
        self.assertEqual(60, sum(cluster["employed_residents"] for cluster in clusters))
        self.assertTrue(all("cluster_index" in radio for radio in radios))


class WorkplaceAggregationTests(unittest.TestCase):
    def test_aggregates_capacity_through_nearest_census_radio(self):
        radios = [
            {"location": (-58.50, -34.60), "cluster_index": 0},
            {"location": (-58.40, -34.60), "cluster_index": 1},
        ]
        clusters = [{"id": "west"}, {"id": "east"}]
        workplaces = [
            {"location": (-58.49, -34.60), "capacity": 100},
            {"location": (-58.48, -34.60), "capacity": 50},
            {"location": (-58.41, -34.60), "capacity": 75},
        ]

        capacities = aggregate_workplaces_to_clusters(workplaces, radios, clusters)

        self.assertEqual([150, 75], capacities.tolist())

    def test_rejects_aggregation_without_radios(self):
        with self.assertRaisesRegex(ValueError, "without census radios"):
            aggregate_workplaces_to_clusters([{"location": (0.0, 0.0), "capacity": 1}], [], [])


class SparseTransportTests(unittest.TestCase):
    def test_preserves_quantized_dense_flow_lower_bounds(self):
        gravity_flows = np.array([85.5, 14.5, 14.5, 85.5], dtype=float)
        sparse = solve_sparse_transport(
            np.array([100, 100], dtype=np.int64),
            np.array([100, 100], dtype=np.int64),
            np.array([0, 0, 1, 1], dtype=np.int64),
            np.array([0, 1, 0, 1], dtype=np.int64),
            gravity_flows,
            flow_quantum=10,
        )

        self.assertTrue(np.all(sparse >= np.floor(gravity_flows / 10) * 10))
        self.assertEqual(200, int(sparse.sum()))

    def test_preserves_integer_marginals_and_prefers_gravity_edges(self):
        origin_targets = np.array([6, 4], dtype=np.int64)
        cell_targets = np.array([5, 5], dtype=np.int64)
        origin_indices = np.array([0, 0, 1, 1], dtype=np.int64)
        cell_indices = np.array([0, 1, 0, 1], dtype=np.int64)
        gravity_flows = np.array([4.5, 1.5, 0.5, 3.5], dtype=float)

        sparse = solve_sparse_transport(
            origin_targets,
            cell_targets,
            origin_indices,
            cell_indices,
            gravity_flows,
        )

        self.assertEqual([6, 4], np.bincount(origin_indices, weights=sparse, minlength=2).astype(int).tolist())
        self.assertEqual([5, 5], np.bincount(cell_indices, weights=sparse, minlength=2).astype(int).tolist())
        self.assertEqual([5, 1, 0, 4], sparse.tolist())

    def test_rejects_an_infeasible_candidate_graph(self):
        with self.assertRaisesRegex(ValueError, "Sparse gravity projection failed"):
            solve_sparse_transport(
                np.array([5, 5], dtype=np.int64),
                np.array([5, 5], dtype=np.int64),
                np.array([0, 1], dtype=np.int64),
                np.array([0, 0], dtype=np.int64),
                np.array([5.0, 5.0]),
            )


class WorkplaceAllocationTests(unittest.TestCase):
    def test_allocates_exact_workplace_capacity_with_sparse_segments(self):
        assignments = allocate_cell_flows(
            [(0, 250), (1, 150)],
            [(10, 300), (11, 100)],
        )

        self.assertEqual([(0, 10, 250), (1, 10, 50), (1, 11, 100)], assignments)

    def test_rejects_mismatched_cell_totals(self):
        with self.assertRaisesRegex(ValueError, "do not reconcile"):
            allocate_cell_flows([(0, 10)], [(10, 9)])

    def test_disaggregates_zone_flows_with_exact_cluster_marginals(self):
        assignments = disaggregate_zone_flows(
            sparse_flows=np.array([200, 100], dtype=np.int64),
            origin_indices=np.array([0, 1], dtype=np.int64),
            destination_indices=np.array([0, 0], dtype=np.int64),
            solver_zones=[
                {"cluster_indices": [0, 1]},
                {"cluster_indices": [2]},
                {"cluster_indices": [3, 4]},
            ],
            destination_zones=[{"zone_index": 2}],
            cluster_origin_targets=np.array([120, 80, 100, 0, 0], dtype=np.int64),
            cluster_capacities=np.array([0, 0, 0, 180, 120], dtype=np.int64),
        )

        self.assertEqual(300, sum(size for _, _, size in assignments))
        self.assertEqual(
            [120, 80, 100, 0, 0],
            np.bincount(
                [origin for origin, _, _ in assignments],
                weights=[size for _, _, size in assignments],
                minlength=5,
            ).astype(int).tolist(),
        )
        self.assertEqual(
            [0, 0, 0, 180, 120],
            np.bincount(
                [destination for _, destination, _ in assignments],
                weights=[size for _, _, size in assignments],
                minlength=5,
            ).astype(int).tolist(),
        )


class DemandEmissionTests(unittest.TestCase):
    def test_merges_coordinates_and_only_caps_individual_populations(self):
        origins = [
            {"id": "origin_a", "location": (1.0, 2.0), "employed_residents": 450},
        ]
        workplaces = [
            {"id": "work_a", "location": (1.0, 2.0), "capacity": 350},
        ]

        demand = build_output_demand(
            origins,
            workplaces,
            [(0, 0, 350)],
            np.array([100], dtype=np.int64),
            maximum_population_size=200,
        )

        self.assertEqual(1, len(demand["points"]))
        point = demand["points"][0]
        self.assertEqual(450, point["residents"])
        self.assertEqual(450, point["jobs"])
        self.assertEqual([200, 150, 100], [pop["size"] for pop in demand["pops"]])
        self.assertEqual(len(demand["pops"]), len(point["popIds"]))
        self.assertEqual(len(point["popIds"]), len(set(point["popIds"])))
        self.assertTrue(all(pop["residenceId"] == pop["jobId"] == point["id"] for pop in demand["pops"]))

    def test_keeps_large_job_total_on_one_native_point(self):
        origins = [
            {"id": "origin_a", "location": (0.0, 0.0), "employed_residents": 500},
        ]
        workplaces = [
            {"id": "work_a", "location": (0.1, 0.1), "capacity": 500},
        ]

        demand = build_output_demand(
            origins,
            workplaces,
            [(0, 0, 500)],
            np.array([0], dtype=np.int64),
            maximum_population_size=200,
        )

        job_points = [point for point in demand["points"] if point["jobs"]]
        self.assertEqual(1, len(job_points))
        self.assertEqual(500, job_points[0]["jobs"])
        self.assertEqual([200, 200, 100], [pop["size"] for pop in demand["pops"]])

    def test_report_uses_the_smallest_emitted_population(self):
        demand = {
            "points": [
                {"id": "a", "location": [0.0, 0.0], "jobs": 1, "residents": 1, "popIds": ["p"]},
            ],
            "pops": [
                {
                    "id": "p",
                    "residenceId": "a",
                    "jobId": "a",
                    "drivingDistance": 0,
                    "size": 1,
                },
            ],
        }

        report = build_demand_report(
            demand,
            np.array([1.0]),
            np.array([1]),
            np.array([0]),
            np.array([0]),
            [{"location": (0.0, 0.0)}],
            [{"location": (0.0, 0.0)}],
            [{"location": (0.0, 0.0), "radio_count": 1, "employed_residents": 1}],
            [(0, 0, 1)],
            employed_total=1,
            formal_total=1,
        )

        self.assertEqual(1, report["output"]["population_size_min"])


if __name__ == "__main__":
    unittest.main()
