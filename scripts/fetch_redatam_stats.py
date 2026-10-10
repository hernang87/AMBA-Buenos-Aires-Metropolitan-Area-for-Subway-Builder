from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

ENDPOINT = "https://redatam.indec.gob.ar/binarg/RpWebStats.exe/AreaList?"
BASE_PARAMS = {
    "MAIN": "WebServerMain.inl",
    "BASE": "CPV2022",
    "LANG": "ESP",
    "CODIGO": "XXUSUARIOXX",
    "ITEM": "AREASHOGPOPART",
    "MODE": "RUN",
    "VARIABLE": "PERSONA.CONDACT",
    "INLINESELECTION": "",
    "TOTROW": "on",
    "OUTPUT": "RADIO",
    "UNIVERSE": "VIVIENDA.TIPOVIVG=1",
    "FILTER": "",
    "TEXT_FILTER": "",
    "FORMAT": "HTML",
    "Submit": "Ejecutar",
}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.current_row = []
        elif tag == "td" and self.current_row is not None:
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.current_row is not None and self.current_cell is not None:
            self.current_row.append("".join(self.current_cell).strip())
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None


def run_with_retries(command: list[str], attempts: int = 3, delay_seconds: float = 2.0, sleep=time.sleep) -> str:
    for attempt in range(1, attempts + 1):
        try:
            return subprocess.run(command, check=True, capture_output=True, text=True).stdout
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            print(f"Warning: attempt {attempt}/{attempts} failed, retrying", file=sys.stderr)
            sleep(delay_seconds * 2 ** (attempt - 1))


def grid_url_from_landing(landing: str) -> str:
    match = re.search(r"<iframe src=['\"]([^'\"]+)['\"]", landing)
    if not match:
        raise RuntimeError("Redatam did not return an output iframe")
    return "https://redatam.indec.gob.ar" + match.group(1)


def parse_grid(grid: str, selection: str) -> list[dict[str, int | str]]:
    parser = TableParser()
    parser.feed(grid)
    def number(value: str) -> int:
        return int(re.sub(r"\D", "", value) or 0)

    results = []
    for row in parser.rows:
        if len(row) < 6 or not re.fullmatch(r"\d{9}", row[1]):
            continue
        results.append({"area_id": row[1], "population": number(row[5]), "jobs": number(row[2])})
    if not results:
        raise RuntimeError(f"Redatam returned no radio rows for {selection}")
    return results


def query(cookie_jar: Path, selection: str, record_dir: Path | None = None) -> list[dict[str, int | str]]:
    params = {**BASE_PARAMS, "SELECTION": selection}
    command = ["curl", "--connect-timeout", "30", "-fsSL", "-c", str(cookie_jar), "-b", str(cookie_jar), "-X", "POST", ENDPOINT]
    for key, value in params.items():
        command.extend(["--data-urlencode", f"{key}={value}"])
    landing = run_with_retries(command)
    grid_url = grid_url_from_landing(landing)
    grid = run_with_retries(["curl", "--connect-timeout", "30", "-fsSL", "-b", str(cookie_jar), grid_url])
    if record_dir is not None:
        record_dir.mkdir(parents=True, exist_ok=True)
        safe = selection.replace("\\", "_").replace(".", "_")
        (record_dir / f"{safe}_landing.html").write_text(landing, encoding="utf-8")
        (record_dir / f"{safe}_grid.html").write_text(grid, encoding="utf-8")
    return parse_grid(grid, selection)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Census 2022 population and occupied people by radio from INDEC Redatam.")
    parser.add_argument("--output", type=Path, default=Path("data/raw/rmba_stats.csv"))
    parser.add_argument("--record-dir", type=Path, default=None)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary_directory:
        cookie_jar = Path(temporary_directory) / "cookies.txt"
        rows = query(cookie_jar, r"Sels\Prov02.sel", args.record_dir) + query(cookie_jar, r"Sels\Prov06.sel", args.record_dir)
    deduplicated = {row["area_id"]: row for row in rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["area_id", "population", "jobs"])
        writer.writeheader()
        writer.writerows(deduplicated.values())
    print(f"Exported {len(deduplicated)} radio statistics to {args.output}")


if __name__ == "__main__":
    main()
