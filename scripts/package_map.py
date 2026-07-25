from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "output/BUE"


def validate_package_identity(output_config: dict, files: list[str]) -> None:
    if output_config.get("code") != "BUE":
        raise ValueError("Packaged config code must be BUE")
    if "BUE.pmtiles" not in files or any(name.startswith("AMBA.") for name in files):
        raise ValueError("Package must contain BUE.pmtiles and no AMBA city assets")


def main() -> None:
    config = json.loads((ROOT / "config/bue.json").read_text(encoding="utf-8"))
    files = ["config.json", "BUE.pmtiles", "buildings_index.json", "buildings_index.bin", "demand_data.json", "roads.geojson", "runways_taxiways.geojson"]
    output_config = json.loads((MAP / "config.json").read_text(encoding="utf-8"))
    try:
        validate_package_identity(output_config, files)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    archive = ROOT / "output/amba.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for name in files:
            path = MAP / name
            if not path.exists():
                raise SystemExit(f"Cannot package missing file: {path}")
            handle.write(path, name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT / "output/amba.sha256").write_text(f"{digest}  amba.zip\n", encoding="utf-8")
    print(f"Packaged {archive} ({config['version']})")


if __name__ == "__main__":
    main()
