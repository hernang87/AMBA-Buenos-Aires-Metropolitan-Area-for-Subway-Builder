import unittest

import numpy as np

from scripts.generate_demand import (
    aggregate_workplaces_to_origins,
    allocate_cell_flows,
    build_demand_report,
    build_output_demand,
    solve_sparse_transport,
)


class WorkplaceAggregationTests(unittest.TestCase):
    def test_aggregates_capacity_to_nearest_census_derived_origin(self):
        origins = [
            {"id": "west", "location": (-58.50, -34.60)},
            {"id": "east", "location": (-58.40, -34.60)},
        ]
        workplaces = [
            {"location": (-58.49, -34.60), "capacity": 100},
            {"location": (-58.48, -34.60), "capacity": 50},
            {"location": (-58.41, -34.60), "capacity": 75},
        ]

        aggregated = aggregate_workplaces_to_origins(workplaces, origins)

        self.assertEqual([150, 75], [workplace["capacity"] for workplace in aggregated])
        self.assertEqual(
            [(-58.50, -34.60), (-58.40, -34.60)],
            [workplace["location"] for workplace in aggregated],
        )

    def test_rejects_aggregation_without_origins(self):
        with self.assertRaisesRegex(ValueError, "without census-derived origins"):
            aggregate_workplaces_to_origins([{"location": (0.0, 0.0), "capacity": 1}], [])


class SparseTransportTests(unittest.TestCase):
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
            employed_total=1,
            formal_total=1,
        )

        self.assertEqual(1, report["output"]["population_size_min"])


if __name__ == "__main__":
    unittest.main()
