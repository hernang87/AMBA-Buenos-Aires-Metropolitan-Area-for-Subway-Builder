from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from .checksums import ROOT, ChecksumError, download, user_agent
else:
    from checksums import ROOT, ChecksumError, download, user_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Download official geocoded formal workplace data.")
    parser.add_argument("--config", type=Path, default=ROOT / "config/bue.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/raw/workplaces.csv")
    parser.add_argument("--force", action="store_true", help="Download even if the file exists.")
    parser.add_argument("--update", action="store_true", help="Accept upstream changes.")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    try:
        download(
            config["workplaces"]["url"],
            args.output,
            user_agent=user_agent(config["version"]),
            update=args.update,
            force=args.force,
        )
    except ChecksumError as error:
        raise SystemExit(str(error))
    print(f"Downloaded workplace data to {args.output}")


if __name__ == "__main__":
    main()
