from __future__ import annotations

import argparse
import csv
import re
import subprocess
import tempfile
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


def query(cookie_jar: Path, selection: str) -> list[dict[str, int | str]]:
    params = {**BASE_PARAMS, "SELECTION": selection}
    command = ["curl", "-fsSL", "-c", str(cookie_jar), "-b", str(cookie_jar), "-X", "POST", ENDPOINT]
    for key, value in params.items():
        command.extend(["--data-urlencode", f"{key}={value}"])
    landing = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    match = re.search(r'<iframe src="([^"]+)"', landing)
    if not match:
        raise RuntimeError("Redatam did not return an output iframe")
    grid_url = "https://redatam.indec.gob.ar" + match.group(1)
    grid = subprocess.run(["curl", "-fsSL", "-b", str(cookie_jar), grid_url], check=True, capture_output=True, text=True).stdout
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Census 2022 population and occupied people by radio from INDEC Redatam.")
    parser.add_argument("--output", type=Path, default=Path("data/raw/rmba_stats.csv"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary_directory:
        cookie_jar = Path(temporary_directory) / "cookies.txt"
        rows = query(cookie_jar, r"Sels\Prov02.sel") + query(cookie_jar, r"Sels\Prov06.sel")
    deduplicated = {row["area_id"]: row for row in rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["area_id", "population", "jobs"])
        writer.writeheader()
        writer.writerows(deduplicated.values())
    print(f"Exported {len(deduplicated)} radio statistics to {args.output}")


if __name__ == "__main__":
    main()
