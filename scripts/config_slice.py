from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SLICE_KEYS = {
    "build": None,
    "demand": ("demand", "bbox", "version"),
    "workplaces": ("workplaces", "bbox"),
}
BUILD_EXCLUDED_KEYS = {"demand", "workplaces", "version", "registry"}


def slice_config(config: dict, name: str) -> dict:
    if name not in SLICE_KEYS:
        raise SystemExit(f"Unknown config slice: {name!r}")
    if name == "build":
        return {key: value for key, value in config.items() if key not in BUILD_EXCLUDED_KEYS}
    return {key: config[key] for key in SLICE_KEYS[name] if key in config}


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a named slice of config/bue.json for make stamps.")
    parser.add_argument("name", help="Slice name: build, demand or workplaces")
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=ROOT / "config/bue.json")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    text = json.dumps(slice_config(config, args.name), indent=2, sort_keys=True) + "\n"

    if args.output.exists() and args.output.read_text(encoding="utf-8") == text:
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
