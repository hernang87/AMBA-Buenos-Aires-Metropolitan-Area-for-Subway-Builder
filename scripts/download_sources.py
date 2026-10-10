from __future__ import annotations

import argparse
import json

if __package__:
    from .checksums import ROOT, ChecksumError, download, user_agent
else:
    from checksums import ROOT, ChecksumError, download, user_agent


SOURCES = {
    "data/raw/rmba_areas.geojson": "https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=geonode:radios_censales2&outputFormat=application/json",
    "data/raw/caba_parcels.geojson": "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/parcelas/parcelas_catastrales.geojson",
    "data/raw/caba_land_use.csv": "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/relevamiento-usos-suelo/relevamiento-usos-del-suelo-2022-2024.csv",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Download raw census and land-use sources.")
    parser.add_argument("targets", nargs="*", choices=list(SOURCES), default=list(SOURCES))
    parser.add_argument("--force", action="store_true", help="Download even if the file exists.")
    parser.add_argument("--update", action="store_true", help="Accept upstream changes.")
    args = parser.parse_args()

    config = json.loads((ROOT / "config/bue.json").read_text(encoding="utf-8"))
    agent = user_agent(config["version"])
    try:
        for key in args.targets:
            download(
                SOURCES[key],
                ROOT / key,
                user_agent=agent,
                update=args.update,
                force=args.force,
            )
    except ChecksumError as error:
        raise SystemExit(str(error))

    print("Save matching INDEC Census 2022 statistics as data/raw/rmba_stats.csv (scripts/fetch_redatam_stats.py).")
    print("Run scripts/fetch_workplace_data.py to download workplace locations and employment bands.")
    print("Run scripts/prepare_caba_anchors.py after preparing census areas.")


if __name__ == "__main__":
    main()
