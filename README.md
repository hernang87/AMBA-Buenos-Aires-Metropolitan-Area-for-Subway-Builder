# AMBA for Subway Builder

Reproducible build pipeline for an Área Metropolitana de Buenos Aires map for Subway Builder and Railyard.

## Inputs

- `argentina-latest.osm.pbf` at the repository root, or another Argentina OSM PBF.
- An INDEC RMBA census-area GeoJSON file.
- A UTF-8 CSV containing `area_id,population,jobs` for the same census areas. `population` is total residents and `jobs` is employed residents used as demand producers.
- The official CEP XXI geocoded formal-workplace CSV, downloaded by `fetch_workplace_data.py`.

The census CSV is intentionally an input rather than checked-in data; record its exact INDEC source in `data/SOURCES.md`.

## Setup

Install Depot and its documented Python/CLI dependencies. The map generator requires `osmium`, `mapshaper`, `tippecanoe`, `tile-join`, `pmtiles`, `planetiler.jar`, `sqlite3`, `jq`, Node.js, Java, and Python geospatial packages.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install numpy shapely git+https://github.com/Subway-Builder-Modded/depot.git
```

Fetch and prepare the machine-readable inputs:

```sh
./scripts/download_sources.sh
python scripts/fetch_redatam_stats.py
python scripts/prepare_census.py --areas data/raw/rmba_areas.geojson --stats data/raw/rmba_stats.csv --output data/processed/areas.csv
python scripts/fetch_workplace_data.py
python scripts/prepare_workplaces.py
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

Demand uses employed residents (`Ocupado`) from the official Census 2022 RMBA census-area export. Formal CEP XXI/SIPA workplace capacity is balanced against scaled employed-resident origins with a doubly constrained gravity model. Establishments sharing a rounded source coordinate are combined, but the 0.005-degree cell is used only as an internal balancing index; exported job points retain dispersed source coordinates. Employment not represented by the formal workplace source is modeled as local residual employment at residential origins. Every exported population and job point is capped at 200. This is modeled demand, not an observed OD matrix, and the workplace source excludes informal, self-employed, domestic, and uncovered public employment.

## Sources

- INDEC Census 2022 RMBA: <https://www.indec.gob.ar/ftp/cuadros/poblacion/censo2022_rmba.pdf>
- INDEC Geoportal: <https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos>
- Depot: <https://github.com/Subway-Builder-Modded/depot>
- Railyard documentation: <https://subwaybuildermodded.com/railyard/docs/v0.2/developers/>
