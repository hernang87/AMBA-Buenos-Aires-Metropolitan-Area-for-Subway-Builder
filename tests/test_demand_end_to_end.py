import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "demand_tiny"
EXPECTED_DATA = FIXTURE_DIR / "expected_demand_data.json"
EXPECTED_REPORT = FIXTURE_DIR / "expected_demand_report.json"

GRID_SIDE = 4
SQUARE_SIDE = 0.01
WEST_EDGE = -58.50
SOUTH_EDGE = -34.62

WORKPLACES = [
    ("work_000000", -58.495, -34.615, 500.0),
    ("work_000001", -58.485, -34.605, 29.5),
    ("work_000002", -58.475, -34.595, 124.5),
    ("work_000003", -58.465, -34.585, 349.5),
    ("work_000004", -58.465, -34.615, 5.0),
    ("work_000005", -58.495, -34.585, 5.0),
]


def square_polygon(west, south, side):
    east = west + side
    north = south + side
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]],
    }


def normalize(value):
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    return value


def write_inputs(root: Path) -> dict[str, Path]:
    areas = root / "areas.csv"
    with areas.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["area_id", "population", "jobs", "geometry"])
        writer.writeheader()
        for k in range(GRID_SIDE * GRID_SIDE):
            row, col = divmod(k, GRID_SIDE)
            jobs = 100 + 10 * k
            writer.writerow({
                "area_id": f"02000{k:04d}",
                "population": 2 * jobs,
                "jobs": jobs,
                "geometry": json.dumps(square_polygon(
                    WEST_EDGE + 0.01 * col, SOUTH_EDGE + 0.01 * row, SQUARE_SIDE
                )),
            })

    anchors = root / "anchors.csv"
    with anchors.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["area_id", "longitude", "latitude"])
        writer.writeheader()
        writer.writerow({"area_id": "020000000", "longitude": -58.498, "latitude": -34.617})

    workplaces = root / "workplaces.csv"
    with workplaces.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "workplace_id", "cell_id", "longitude", "latitude", "employment_weight", "establishments",
        ])
        writer.writeheader()
        for workplace_id, longitude, latitude, weight in WORKPLACES:
            writer.writerow({
                "workplace_id": workplace_id,
                "cell_id": "cell_0_0",
                "longitude": longitude,
                "latitude": latitude,
                "employment_weight": weight,
                "establishments": 1,
            })

    with (ROOT / "config" / "bue.json").open(encoding="utf-8") as handle:
        real_demand = json.load(handle)["demand"]
    demand = dict(real_demand)
    demand["display_cluster_count"] = 8
    config = root / "config.json"
    config.write_text(json.dumps({
        "version": "0.0.0-test",
        "bbox": [-58.6, -34.7, -58.4, -34.5],
        "demand": demand,
    }, indent=2) + "\n", encoding="utf-8")

    out = root / "out"
    out.mkdir()
    (out / "config.json").write_text(json.dumps(
        {"code": "BUE", "population": 0, "version": "old"}, indent=2
    ) + "\n", encoding="utf-8")

    return {
        "areas": areas,
        "anchors": anchors,
        "workplaces": workplaces,
        "config": config,
        "out": out,
    }


class DemandEndToEndTests(unittest.TestCase):
    def test_generates_demand_matching_golden_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = write_inputs(Path(directory))
            out = paths["out"]
            output = out / "demand_data.json"

            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "generate_demand.py"),
                    "--areas", str(paths["areas"]),
                    "--workplaces", str(paths["workplaces"]),
                    "--anchors", str(paths["anchors"]),
                    "--config", str(paths["config"]),
                    "--output", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=ROOT,
            )

            demand = json.loads(output.read_text(encoding="utf-8"))
            report_path = out / "demand_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            output_config = json.loads((out / "config.json").read_text(encoding="utf-8"))

            self.assertEqual(8, report["output"]["points"])
            self.assertEqual(2800, sum(point["residents"] for point in demand["points"]))
            self.assertEqual(2800, report["totals"]["employed"])
            self.assertEqual(
                sum(pop["size"] for pop in demand["pops"]),
                output_config["population"],
            )
            self.assertEqual("0.0.0-test", output_config["version"])

            if os.environ.get("BUE_UPDATE_GOLDEN") == "1":
                FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(output, EXPECTED_DATA)
                shutil.copyfile(report_path, EXPECTED_REPORT)
                return

            expected_data = json.loads(EXPECTED_DATA.read_text(encoding="utf-8"))
            expected_report = json.loads(EXPECTED_REPORT.read_text(encoding="utf-8"))
            report["output"].pop("demand_json_bytes", None)
            expected_report["output"].pop("demand_json_bytes", None)

            self.assertEqual(normalize(expected_data), normalize(demand))
            self.assertEqual(normalize(expected_report), normalize(report))


if __name__ == "__main__":
    unittest.main()
