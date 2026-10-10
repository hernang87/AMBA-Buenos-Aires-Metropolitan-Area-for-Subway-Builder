# Buenos Aires (BUE) for Subway Builder

Reproducible build pipeline for an Área Metropolitana de Buenos Aires map played in Subway Builder and distributed through the Railyard mod manager.

Naming: AMBA is the geographic region. `BUE` is the in-game city code and the PMTiles asset name. `amba` is the Railyard registry ID and the archive name `output/amba.zip`, kept unchanged for Registry compatibility.

## Inputs

- `argentina-latest.osm.pbf` at the repository root or in `data/raw/`, or another Argentina OSM PBF set with `OSM_PBF`, for roads and geographic context.
- An INDEC RMBA census-area GeoJSON file.
- A UTF-8 CSV containing `area_id,population,jobs` for the same census areas. `population` is total residents and `jobs` is employed residents used as demand producers.
- The official CEP XXI geocoded formal-workplace CSV, downloaded by `fetch_workplace_data.py`.
- Overture building footprints, queried during the map build and processed by Depot.
- CABA cadastral parcel polygons and the 2022–2024 land-use survey for residential placement within census radios.

The census CSV is intentionally an input rather than checked-in data; record its exact INDEC source in `data/SOURCES.md`. The build applies Depot's 40 m² footprint threshold at the Overture query, strips unused attributes, and caps Mapshaper at 8 GB before Depot creates its native indexes and tiles.

## Setup

Install Depot and its documented Python/CLI dependencies. The map generator requires `osmium`, `mapshaper`, `tippecanoe`, `tile-join`, `pmtiles`, `planetiler.jar`, `sqlite3`, `jq`, Node.js, Java, and Python geospatial packages.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

`requirements.txt` records the tested Python dependency versions, including Depot's exact commit. The environment was verified with Python 3.13 on macOS. If an existing `.venv` points to a removed Python installation, move it aside and recreate it with the commands above.

## Quick start

The Makefile drives the whole pipeline. Run it from the repository root with the venv from Setup active or `PYTHON` pointing at your interpreter.

```sh
make            # full pipeline, up to output/amba.zip
make mark-built # adopt already-prepared inputs, map build and demand artifacts as up to date, so only packaging reruns
make verify     # check data/raw files against data/checksums.json
```

Individual stages (each target is a Makefile target; see the Makefile for the exact prerequisites):

- `make download`: fetch the raw inputs in `data/raw/` that are missing.
- `make prepare`: write `data/processed/areas.csv`, `workplaces.csv`, and `caba_anchors.csv`.
- `make build`: run `scripts/build_map.py` (Depot map build, stamped at `output/BUE/.build.stamp`).
- `make demand`: write `output/BUE/demand_data.json`.
- `make validate`: run `scripts/validate_map.py`.
- `make package`: write `output/amba.zip` (the default `make` target is `all`, which is the same as `package`).
- `make regions`: prepare the Subway Builder Regions datasets (see Extras below).
- `make gallery`: export preview PNGs (see Extras below).
- `make test`, `make lint`, `make check` (test and lint): see Development.
- `make verify`: see Input verification.
- `make mark-built`: see above.

Stages are tracked by stamps and config slices. Each config section is written to `output/.config/<name>.json` (`build`, `demand`, `workplaces`) by `scripts/config_slice.py`, and a stage reruns only when the slice it uses changes. For example, bumping `version` in `config/bue.json` reruns demand and packaging but not the Depot build, because `version` is excluded from the build slice. Packaging also depends on `config/bue.json` directly, so it reruns on any config edit.

## Environment variables

- `OSM_PBF`: path to the Argentina OSM PBF used by `build_map.py`. When set, it overrides `osmpbf` in `config/bue.json`; relative paths resolve from the repository root.
- `DEPOT_RAM_GB`: memory limit in GB passed to Depot (`RAM`), which sets the Mapshaper Node heap. Default `8`.
- `DEPOT_NCORES`: worker count passed to Depot. Default is `depot.ncores` in `config/bue.json` (currently `4`).
- `OVERTURE_REFRESH`: default `1`. Set `0` to reuse the cached Overture export in `output/BUE/` when the cached release matches the latest release. The latest release is still looked up from the Overture catalog.
- `DEPOT_PATH`: directory of a local Depot checkout. `build_map.py` prepends it to `sys.path`, so it takes precedence over an installed `depot` package.
- `PYTHON`: interpreter used by the Makefile. Default `.venv/bin/python`.

## Input verification

`data/checksums.json` records a SHA-256 for each file in `data/raw/` under one of three policies:

- `pinned`: the download must match the recorded hash; a mismatch fails.
- `record`: the hash is saved on first fetch; a later mismatch fails unless `--update` is given.
- `volatile`: upstream bytes change on every fetch; an existing file is kept unless `--force` is given, and the hash is informational.

Commands:

- `python scripts/checksums.py verify [KEY...]` reports each file as `match`, `mismatch`, `missing`, `unrecorded`, or `changed` (volatile); it exits non-zero on a mismatch. `make verify` runs it for all listed files.
- `python scripts/checksums.py record KEY...` records the current hash of the listed files.
- `scripts/download_sources.py` and `scripts/fetch_workplace_data.py` accept `--update` (accept an upstream change for `pinned` and `record` files, which otherwise fail) and `--force` (re-download a file that already exists, which is how `volatile` files are refreshed).

See [data/SOURCES.md](data/SOURCES.md#checksums) for details.

## Manual steps

The Makefile is the supported path. The commands below are the equivalent manual sequence. `scripts/download_sources.sh` is a thin wrapper that runs `python scripts/download_sources.py`, so either works.

Fetch and prepare the machine-readable inputs:

```sh
python scripts/download_sources.py
python scripts/fetch_redatam_stats.py
python scripts/prepare_census.py --areas data/raw/rmba_areas.geojson --stats data/raw/rmba_stats.csv --output data/processed/areas.csv
python scripts/fetch_workplace_data.py
python scripts/prepare_workplaces.py
python scripts/prepare_caba_anchors.py
```

Build and package:

```sh
python scripts/build_map.py
python scripts/generate_demand.py
python scripts/validate_map.py
python scripts/package_map.py
```

Packaging runs the map validator before replacing the archive. Validation reconstructs display clusters from the processed census and CABA anchors, and checks each exported point's identity, position, and resident count against those sources.

The final archive is written to `output/amba.zip`. The registry map ID remains `amba`, while the packaged city code and PMTiles asset use `BUE`. The archive ships the binary building index required by current Subway Builder releases. The build puts college areas in `commercial` with `type: college`, and park and aerodrome polygons in the `parks` and `airports` tile layers read by Subway Builder 1.7.1.

The release includes `output/amba.zip`, `output/amba.sha256`, and `output/manifest.json` as separate assets. The Registry reads the manifest's `subway-builder` dependency range for maps as well as mods. The manifest is not inside the map ZIP.

## Extras: regions and gallery

`python scripts/prepare_regions.py` (or `make regions`) reads `data/raw/rmba_areas.geojson` and `data/processed/areas.csv` and writes `output/BUE-regions/`, containing `radios-censales.geojson` (one feature per census radio), `partidos.geojson`, and `comunas.geojson` (radios dissolved by partido or CABA comuna, with summed population and jobs), plus a `README.txt`. It also writes `output/BUE-regions.zip`, which packages the same files. Copy the GeoJSON files into the Subway Builder Regions mod directory as described in that README.

`python scripts/export_gallery.py --roads <roads.geojson> --regions <regions dir>` writes PNG previews to `output/gallery/` by default (`--output` changes it). Both `--roads` and `--regions` are required. `make gallery` passes `output/BUE/roads.geojson` and `output/BUE-regions`, so run `make regions` first and build the map before running it.

## Development

`make check` runs the unit tests and ruff (`make test` and `make lint`). Tests use `python -m unittest discover -s tests`, which must be run from the repository root.

CI (`.github/workflows/ci.yml`) runs the same lint and test commands on Python 3.13 with `requirements-ci.txt`. CI does not need Depot or the raw inputs.

## Project docs

- [CHANGELOG.md](CHANGELOG.md): release history.
- [NOTICE.md](NOTICE.md): third-party attribution and license status.
- [data/SOURCES.md](data/SOURCES.md): exact source URLs, retrieval dates, filtering, and checksums for each input.
- [docs/adr/](docs/adr/): architecture decision records.

## Demand model

Demand uses employed residents (`Ocupado`) from the official Census 2022 RMBA census-area export. Formal CEP XXI/SIPA workplace capacity is balanced against scaled employed-resident origins with a doubly constrained gravity model. The dense gravity matrix is projected onto a sparse exact transportation solution that preserves every origin and workplace-cell total while favoring the highest-probability gravity edges.

The workplace source publishes coordinates rounded to 0.001 degrees. Exporting those locations directly creates a misleading regular lattice. Demand generation instead builds 6,000 adaptive display clusters from the 18,018 census radios and assigns each workplace through its nearest radio. The regular 0.02-degree zones remain internal to the gravity solve and are never exported as points. Employment not represented by the formal workplace source is modeled as local residual employment at residential clusters.

Within CABA, display-cluster positions use active residential parcels from the city's 2022–2024 land-use survey, weighted by their reported floor count. Census radios without matching parcels retain their original representative point. This refines where modeled demand is drawn without changing census totals, workplace assignments, solver zones, or claiming parcel-level resident counts. The parcel and survey files are build inputs; they are not shipped in the map package.

Only individual population records are capped at 200. A demand point may contain more than 200 residents or jobs, and all roles in an adaptive cluster share one point. The build fails if it produces more than 100,000 population records. `output/BUE/demand_report.json` records solver, clustering, cardinality, population-size, and commute-distance diagnostics. This is modeled demand, not an observed OD matrix, and the workplace source excludes informal, self-employed, domestic, and uncovered public employment.

Run the focused regression suite with:

```sh
python -m unittest discover -s tests
```

The demand code lives in `scripts/demand/` (clustering, transport, output, and pipeline modules) behind the `scripts/generate_demand.py` entry point.

## Sources

- INDEC Census 2022 RMBA: <https://www.indec.gob.ar/ftp/cuadros/poblacion/censo2022_rmba.pdf>
- INDEC Geoportal: <https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos>
- Depot: <https://github.com/Subway-Builder-Modded/depot>
- CABA cadastral parcels: <https://data.buenosaires.gob.ar/es/dataset/parcelas>
- CABA 2022–2024 land-use survey: <https://data.buenosaires.gob.ar/es/dataset/relevamiento-usos-suelo>
- Railyard documentation: <https://subwaybuildermodded.com/railyard/docs/v0.2/developers/>
