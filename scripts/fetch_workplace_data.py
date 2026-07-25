from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Download official geocoded formal workplace data.")
    parser.add_argument("--config", type=Path, default=ROOT / "config/bue.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw/workplaces.csv")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    url = config["workplaces"]["url"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "BUE-Subway-Builder/0.3"})
    with urlopen(request) as response, args.output.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
    print(f"Downloaded workplace data to {args.output}")


if __name__ == "__main__":
    main()
