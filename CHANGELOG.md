# Changelog

Versions 0.3.x are not tagged in git; dates TODO(owner). Earlier releases: git tags v0.1.0–v0.2.4.

## 0.3.3

- CABA parcel/land-use display placement of residential demand points.
- Parks and airports tile layers for Subway Builder 1.7.1.
- Registry `output/manifest.json` with `subway-builder >=1.7.1`.
- Pinned `requirements.txt` and source-cluster validation before packaging.

## 0.3.2

The v0.3.2 release changes only the map version and release metadata so the Registry can identify its Subway Builder compatibility range.

## 0.3.1

The v0.3.1 compatibility release reuses the v0.3.0 OSM, Overture 2026-07-22.0, census, and workplace inputs. It rebuilds the basemap tile translation from the retained `bue-clean.mbtiles` with Depot 1.2.7, preserving the building and demand data while moving college, university, and school polygons into the game's commercial tile layer.

## 0.3.0

The v0.3.0 build applies Depot v1.2.3's 40 m² minimum footprint threshold before materialization, exports only geometry and height, then uses Depot's 1 m simplification, native indexes, and tile generation with an 8 GB Mapshaper cap.
