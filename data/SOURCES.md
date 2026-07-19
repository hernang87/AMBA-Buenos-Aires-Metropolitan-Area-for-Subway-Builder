# AMBA source inputs

Record the exact download URL, retrieval date, license, and filtering or aggregation used for every file in `data/raw/`.

## Required inputs

### `rmba_areas.geojson`

INDEC 2022 census-area geometry covering CABA and the 39 partidos in the Región Metropolitana Buenos Aires. The geometry must contain a stable area identifier in `area_id`, `cod_indec`, or `id`.

The INDEC GeoNode WFS layer `geonode:radios_censales2` is available at:

`https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=geonode:radios_censales2&outputFormat=application/json`

### `rmba_stats.csv`

UTF-8 CSV with one row per geometry identifier and at least these columns:

`area_id,population`

`population` is resident population. The legacy `jobs` column may be present for the separate regions export, but it is no longer used to locate workplace destinations.

The repository exporter `scripts/fetch_redatam_stats.py` queries the INDEC Redatam Census 2022 `PERSONA.CONDACT` table at `RADIO` level for CABA and Buenos Aires province and maps the `Total` column to `population`; it retains `Ocupado` as a legacy `jobs` column for the regions export. `prepare_census.py` then filters the result to the AMBA bounding box. `Ocupado` is not used as a workplace-location variable because it describes employed residents, not workplace locations.

### `workplaces.csv`

The workplace input is the official [CEP XXI/SIPA distribution of productive establishments](https://cdn.produccion.gob.ar/cdn-cep/establecimientos-productivos/distribucion_establecimientos_productivos_sexo.csv), published by the Ministry of Economy and the Ministry of Labour. It contains rounded WGS84 coordinates, year, sector, and grouped employment per establishment. The source methodology states that employment is assigned to the establishment's registered workplace address and that the published data covers formal registered salaried employment.

`scripts/fetch_workplace_data.py` downloads the source; `scripts/prepare_workplaces.py` filters to 2022 and the AMBA bounding box, then converts employment bands to destination weights: `1–9 → 5`, `10–49 → 29.5`, `50–199 → 124.5`, `200–499 → 349.5`, and `500+ → 500` as a conservative lower-bound assumption. Establishments are aggregated into the configured 0.02-degree grid using employment-weighted coordinates.

## Existing local input

`argentina-latest.osm.pbf` is the current local OSM extract used by default. Replace it with a newer extract when rebuilding and record its source date here.
