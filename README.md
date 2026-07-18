# AMBA for Subway Builder

Reproducible build pipeline for an Área Metropolitana de Buenos Aires map for Subway Builder and Railyard.

## Inputs

- `argentina-latest.osm.pbf` at the repository root, or another Argentina OSM PBF.
- An INDEC RMBA census-area GeoJSON file.
- A UTF-8 CSV containing `area_id,population,jobs` for the same areas.

The census CSV is intentionally an input rather than checked-in data; record its exact INDEC source in `data/SOURCES.md`.

## Setup

Install Depot and its documented Python/CLI dependencies. The map generator requires `osmium`, `mapshaper`, `tippecanoe`, `tile-join`, `pmtiles`, `planetiler.jar`, `sqlite3`, `jq`, Node.js, Java, and Python geospatial packages.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install git+https://github.com/Subway-Builder-Modded/depot.git
```

Fetch and prepare the machine-readable inputs:

```sh
./scripts/download_sources.sh
python scripts/fetch_redatam_stats.py
python scripts/prepare_census.py --areas data/raw/rmba_areas.geojson --stats data/raw/rmba_stats.csv --output data/processed/areas.csv
```

Build and package:

```sh
python scripts/build_map.py
python scripts/generate_demand.py
python scripts/validate_map.py
python scripts/package_map.py
```

The final archive is written to `output/AMBA.zip`.

## Demand model

Demand uses official Census 2022 population and employment aggregates by RMBA area. Each area becomes a spatial demand point at its representative centroid. Residents are assigned to jobs with a documented distance-weighted synthetic OD model in Depot's `points`/`pops` format. It is not an observed trip matrix.

## Sources

- INDEC Census 2022 RMBA: <https://www.indec.gob.ar/ftp/cuadros/poblacion/censo2022_rmba.pdf>
- INDEC Geoportal: <https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos>
- Depot: <https://github.com/Subway-Builder-Modded/depot>
- Railyard documentation: <https://subwaybuildermodded.com/railyard/docs/v0.2/developers/>
