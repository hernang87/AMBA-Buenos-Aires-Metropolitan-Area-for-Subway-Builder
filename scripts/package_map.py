from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "output/AMBA"


def main() -> None:
    config = json.loads((ROOT / "config/amba.json").read_text(encoding="utf-8"))
    files = ["config.json", "AMBA.pmtiles", "buildings_index.json", "buildings_index.bin", "demand_data.json", "roads.geojson", "runways_taxiways.geojson"]
    archive = ROOT / "output/AMBA.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as handle:
        for name in files:
            path = MAP / name
            if not path.exists():
                raise SystemExit(f"Cannot package missing file: {path}")
            handle.write(path, name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT / "output/AMBA.sha256").write_text(f"{digest}  AMBA.zip\n", encoding="utf-8")
    print(f"Packaged {archive} ({config['version']})")


if __name__ == "__main__":
    main()
