# Changelog

Release dates come from the GitHub releases. Earlier releases: git tags v0.1.0–v0.2.5.

## 0.3.4

Tooling and documentation release. The map data (PMTiles, building index, roads, demand) is unchanged from 0.3.3; only the version string in `config.json` differs.

- Input verification: `data/checksums.json` with `pinned`, `record` and `volatile` policies, checked by `scripts/checksums.py` and enforced by `download_sources.py` and `fetch_workplace_data.py`.
- `Makefile` pipeline with per-stage config slices, so config edits rebuild only affected stages; `make mark-built` adopts existing artifacts.
- GitHub Actions CI (ruff and unit tests, no Depot required) and `ruff.toml`.
- Game compatibility range (`registry.subway_builder`) and Depot core count (`depot.ncores`, overridable with `DEPOT_NCORES`) moved into `config/bue.json`; the OSM extract may live in `data/raw/`.
- `generate_demand.py` split into the `scripts/demand/` package with byte-identical output, plus an end-to-end golden test on a synthetic city.
- Redatam fetcher retries and recorded-fixture tests; gallery and region scripts anchored at the repository root and tracked.
- Release history moved out of `data/SOURCES.md`; `NOTICE.md` records attribution and open license questions.

## 0.3.3 (2026-09-25)

- CABA parcel/land-use display placement of residential demand points.
- Parks and airports tile layers for Subway Builder 1.7.1.
- Registry `output/manifest.json` with `subway-builder >=1.7.1`.
- Pinned `requirements.txt` and source-cluster validation before packaging.

## 0.3.2 (2026-09-24)

The v0.3.2 release changes only the map version and release metadata so the Registry can identify its Subway Builder compatibility range.

## 0.3.1 (2026-09-24)

The v0.3.1 compatibility release reuses the v0.3.0 OSM, Overture 2026-07-22.0, census, and workplace inputs. It rebuilds the basemap tile translation from the retained `bue-clean.mbtiles` with Depot 1.2.7, preserving the building and demand data while moving college, university, and school polygons into the game's commercial tile layer.

## 0.3.0 (2026-07-25)

The v0.3.0 build applies Depot v1.2.3's 40 m² minimum footprint threshold before materialization, exports only geometry and height, then uses Depot's 1 m simplification, native indexes, and tile generation with an 8 GB Mapshaper cap.
