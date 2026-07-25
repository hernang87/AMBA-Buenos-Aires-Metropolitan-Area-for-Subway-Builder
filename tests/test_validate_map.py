import unittest

from scripts.validate_map import validate_demand, validate_report


def valid_fixture():
    config = {"bbox": [-1.0, -1.0, 1.0, 1.0], "population": 500}
    demand = {
        "points": [
            {
                "id": "origin",
                "location": [0.0, 0.0],
                "jobs": 0,
                "residents": 500,
                "popIds": ["pop_0", "pop_1", "pop_2"],
            },
            {
                "id": "job",
                "location": [0.5, 0.5],
                "jobs": 500,
                "residents": 0,
                "popIds": ["pop_0", "pop_1", "pop_2"],
            },
        ],
        "pops": [
            {"id": "pop_0", "residenceId": "origin", "jobId": "job", "size": 200},
            {"id": "pop_1", "residenceId": "origin", "jobId": "job", "size": 200},
            {"id": "pop_2", "residenceId": "origin", "jobId": "job", "size": 100},
        ],
    }
    return config, demand


class DemandValidationTests(unittest.TestCase):
    def test_accepts_large_point_job_totals(self):
        config, demand = valid_fixture()

        summary = validate_demand(
            config,
            demand,
            maximum_population_size=200,
            maximum_population_count=3,
            allowed_job_locations={(0.5, 0.5)},
        )

        self.assertEqual({"points": 2, "populations": 3, "population": 500}, summary)

    def test_rejects_duplicate_coordinates(self):
        config, demand = valid_fixture()
        demand["points"][1]["location"] = [0.0, 0.0]

        with self.assertRaisesRegex(ValueError, "Duplicate demand point coordinate"):
            validate_demand(config, demand, maximum_population_size=200, maximum_population_count=3)

    def test_rejects_inconsistent_point_population_ids(self):
        config, demand = valid_fixture()
        demand["points"][1]["popIds"].pop()

        with self.assertRaisesRegex(ValueError, "popIds do not reconcile"):
            validate_demand(config, demand, maximum_population_size=200, maximum_population_count=3)

    def test_rejects_per_point_totals_that_only_reconcile_globally(self):
        config, demand = valid_fixture()
        demand["points"][0]["residents"] = 499
        demand["points"][0]["jobs"] = 1
        demand["points"][1]["residents"] = 1
        demand["points"][1]["jobs"] = 499

        with self.assertRaisesRegex(ValueError, "Point resident total does not reconcile"):
            validate_demand(config, demand, maximum_population_size=200, maximum_population_count=3)

    def test_rejects_population_budget_overrun(self):
        config, demand = valid_fixture()

        with self.assertRaisesRegex(ValueError, "Population count exceeds 2"):
            validate_demand(config, demand, maximum_population_size=200, maximum_population_count=2)

    def test_rejects_oversized_population(self):
        config, demand = valid_fixture()
        demand["pops"][0]["size"] = 201

        with self.assertRaisesRegex(ValueError, "Population size exceeds 200"):
            validate_demand(config, demand, maximum_population_size=200, maximum_population_count=3)

    def test_rejects_a_job_outside_census_derived_demand_zones(self):
        config, demand = valid_fixture()

        with self.assertRaisesRegex(ValueError, "not a census-derived demand zone"):
            validate_demand(
                config,
                demand,
                maximum_population_size=200,
                maximum_population_count=3,
                allowed_job_locations={(0.75, 0.75)},
            )


class DemandReportValidationTests(unittest.TestCase):
    def test_accepts_cardinality_and_commute_drift_within_budget(self):
        validate_report(
            {
                "model": {
                    "dense_formal_mean_km": 12.0,
                    "dense_formal_p90_km": 22.0,
                    "sparse_formal_mean_km": 13.5,
                    "sparse_formal_p90_km": 25.0,
                },
                "output": {"duplicate_coordinates": 0, "populations": 100},
            },
            maximum_population_count=250,
        )

    def test_rejects_excessive_mean_commute_drift(self):
        with self.assertRaisesRegex(ValueError, "mean commute drift"):
            validate_report(
                {
                    "model": {
                        "dense_formal_mean_km": 12.0,
                        "dense_formal_p90_km": 22.0,
                        "sparse_formal_mean_km": 14.1,
                        "sparse_formal_p90_km": 25.0,
                    },
                    "output": {"duplicate_coordinates": 0, "populations": 100},
                },
                maximum_population_count=250,
            )


if __name__ == "__main__":
    unittest.main()
