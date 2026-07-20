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

`population` is resident population and `jobs` is employed residents (`Ocupado`), used as the trip-producing population for demand generation. The `jobs` column does not locate workplaces.

The repository exporter `scripts/fetch_redatam_stats.py` queries the INDEC Redatam Census 2022 `PERSONA.CONDACT` table at `RADIO` level for CABA and Buenos Aires province and maps the `Total` column to `population` and `Ocupado` to `jobs`. `prepare_census.py` then filters the result to the AMBA bounding box. `Ocupado` is used as the trip-producing population, not as a workplace-location variable, because it describes employed residents rather than workplace locations.

### `workplaces.csv`

The workplace input is the official [CEP XXI/SIPA distribution of productive establishments](https://cdn.produccion.gob.ar/cdn-cep/establecimientos-productivos/distribucion_establecimientos_productivos_sexo.csv), published by the Ministry of Economy and the Ministry of Labour. It contains rounded WGS84 coordinates, year, sector, and grouped employment per establishment. The source methodology states that employment is assigned to the establishment's registered workplace address and that the published data covers formal registered salaried employment.

`scripts/fetch_workplace_data.py` downloads the source; `scripts/prepare_workplaces.py` filters to 2022 and the AMBA bounding box, groups establishments sharing the same rounded source coordinate, and converts employment bands to destination capacities: `1–9 → 5`, `10–49 → 29.5`, `50–199 → 124.5`, `200–499 → 349.5`, and `500+ → 500` as a conservative lower-bound assumption. The configured 0.005-degree cell is used only as an internal balancing index; the generated job points remain dispersed at the grouped source coordinates.

Demand first balances formal workplace capacity against scaled residence-based employed residents with a distance-constrained iterative proportional fitting model. The difference between total employed residents and formal workplace capacity is represented as local residual employment at residential origins because the source does not locate those jobs. Exported populations and job points are split into groups of at most 200 for game compatibility.

## Existing local input

`argentina-latest.osm.pbf` is the current local OSM extract used by default. Replace it with a newer extract when rebuilding and record its source date here.
