# ADR-0004: Restore Native Depot Building Processing

## Status

Accepted

## Context

The v0.2.x build replaced Depot's building stage with a custom extraction of `building` tags from the local OSM PBF. It indexed 177,890 footprints and omitted substantial coverage available from Depot's normal Overture source. The current Overture release contains approximately 5.69 million raw footprints inside the map bounding box before Depot's area and geometry filters.

The merged registry listing also assigns city code `BUE`, while the package used code `AMBA` and `AMBA.pmtiles`.

## Decision

Use Depot v1.2.3's native building pipeline with a fresh Overture download, its default 40 m² minimum footprint area, 1 m simplification, 12 GB processing limit, and foundations disabled. Remove all custom OSM building extraction and building-index/tile overrides.

Use `BUE` for the Depot city, output directory, packaged config code, PMTiles filename, and generated city assets. Retain `amba` only for the existing registry map ID and lowercase release archive name.

The release validator requires matching JSON and binary building counts greater than the previous 177,890-building output.

## Consequences

### Positive

- Restores current Depot building coverage.
- Keeps building cleanup and tile generation aligned with the supported toolchain.
- Resolves the registry city-code and PMTiles integrity warning.
- Adds a measurable regression gate for future releases.

### Negative

- The Overture download and full building build require substantial time, disk, and memory.
- The packaged building indexes and PMTiles will be larger.

### Neutral

- OSM remains the source for roads and geographic context.
- The registry ID remains `amba`.
