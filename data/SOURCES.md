# AMBA source inputs

Record the exact download URL, retrieval date, license, and filtering or aggregation used for every file in `data/raw/`.

## Required inputs

### `rmba_areas.geojson`

INDEC 2022 census-area geometry covering CABA and the 39 partidos in the Región Metropolitana Buenos Aires. The geometry must contain a stable area identifier in `area_id`, `cod_indec`, or `id`.

The INDEC GeoNode WFS layer `geonode:radios_censales2` is available at:

`https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=geonode:radios_censales2&outputFormat=application/json`

### `rmba_stats.csv`

UTF-8 CSV with one row per geometry identifier and these columns:

`area_id,population,jobs`

`population` is resident population. `jobs` is the employed-person/job proxy selected from the same Census 2022 geography. If official statistics are only available at partido/comuna level, repeat the aggregate across constituent census areas using population weights before running `prepare_census.py`.

The repository exporter `scripts/fetch_redatam_stats.py` queries the INDEC Redatam Census 2022 `PERSONA.CONDACT` table at `RADIO` level for CABA and Buenos Aires province. It maps the `Total` column to `population` and `Ocupado` to `jobs`; `prepare_census.py` then filters the result to the AMBA bounding box.

## Existing local input

`argentina-latest.osm.pbf` is the current local OSM extract used by default. Replace it with a newer extract when rebuilding and record its source date here.
