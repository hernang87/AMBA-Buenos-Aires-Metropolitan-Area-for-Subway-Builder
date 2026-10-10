import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import fetch_redatam_stats

FIXTURES = Path(__file__).parent / "fixtures" / "redatam"
SELECTION = r"Sels\Prov02.sel"


class RedatamParsingTests(unittest.TestCase):
    def test_parse_grid_reads_radio_rows(self):
        grid = (FIXTURES / "grid.html").read_text(encoding="utf-8")
        self.assertEqual(
            fetch_redatam_stats.parse_grid(grid, SELECTION),
            [
                {"area_id": "020070101", "population": 188, "jobs": 128},
                {"area_id": "020070201", "population": 2453, "jobs": 1298},
            ],
        )

    def test_parse_grid_without_radio_rows_raises(self):
        with self.assertRaisesRegex(RuntimeError, "no radio rows"):
            fetch_redatam_stats.parse_grid("<html><table><tr><td>Total</td></tr></table></html>", SELECTION)

    def test_grid_url_from_landing(self):
        landing = (FIXTURES / "landing.html").read_text(encoding="utf-8")
        self.assertEqual(
            fetch_redatam_stats.grid_url_from_landing(landing),
            "https://redatam.indec.gob.ar/binarg/tmp/out.htm",
        )

    def test_grid_url_without_iframe_raises(self):
        with self.assertRaisesRegex(RuntimeError, "output iframe"):
            fetch_redatam_stats.grid_url_from_landing("<html></html>")


class RunWithRetriesTests(unittest.TestCase):
    def test_retry_succeeds_after_one_failure(self):
        sleeps: list[float] = []
        failure = subprocess.CalledProcessError(22, ["curl"])
        success = subprocess.CompletedProcess(["curl"], 0, stdout="ok", stderr="")
        with patch.object(fetch_redatam_stats.subprocess, "run", side_effect=[failure, success]) as run:
            output = fetch_redatam_stats.run_with_retries(["curl"], sleep=sleeps.append)
        self.assertEqual(output, "ok")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(sleeps, [2.0])

    def test_three_failures_reraise(self):
        sleeps: list[float] = []
        failure = subprocess.CalledProcessError(22, ["curl"])
        with (
            patch.object(fetch_redatam_stats.subprocess, "run", side_effect=[failure, failure, failure]) as run,
            self.assertRaises(subprocess.CalledProcessError),
        ):
            fetch_redatam_stats.run_with_retries(["curl"], sleep=sleeps.append)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleeps, [2.0, 4.0])


if __name__ == "__main__":
    unittest.main()
