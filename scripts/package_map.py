from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "output/BUE"
GAME_VERSION = ">=1.7.1"


def validate_package_identity(output_config: dict, files: list[str], version: str) -> None:
    if output_config.get("code") != "BUE":
        raise ValueError("Packaged config code must be BUE")
    if "BUE.pmtiles" not in files or any(name.startswith("AMBA.") for name in files):
        raise ValueError("Package must contain BUE.pmtiles and no AMBA city assets")
    if "buildings_index.bin" not in files or "buildings_index.json" in files:
        raise ValueError("Package must contain only the binary building index")
    if output_config.get("version") != version:
        raise ValueError(f"Packaged config version must be {version}")


def main() -> None:
    config = json.loads((ROOT / "config/bue.json").read_text(encoding="utf-8"))
    files = [
        "config.json", "BUE.pmtiles", "buildings_index.bin",
        "demand_data.json", "roads.geojson", "runways_taxiways.geojson",
    ]
    output_config = json.loads((MAP / "config.json").read_text(encoding="utf-8"))
    try:
        validate_package_identity(output_config, files, config["version"])
    except ValueError as error:
        raise SystemExit(str(error)) from error
    missing = [name for name in files if not (MAP / name).is_file()]
    if missing:
        raise SystemExit(f"Cannot package missing files: {', '.join(missing)}")
    archive = ROOT / "output/amba.zip"
    temporary = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for name in files:
            handle.write(MAP / name, name)
    temporary.replace(archive)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    (ROOT / "output/amba.sha256").write_text(f"{digest}  amba.zip\n", encoding="utf-8")
    (ROOT / "output/manifest.json").write_text(
        json.dumps({"dependencies": {"subway-builder": GAME_VERSION}}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Packaged {archive} ({config['version']})")


if __name__ == "__main__":
    main()
