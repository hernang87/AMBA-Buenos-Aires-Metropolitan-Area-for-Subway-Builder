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

The workplace input is the official [CEP XXI/SIPA distribution of productive establishments](https://cdn.produccion.gob.ar/cdn-cep/establecimientos-productivos/distribucion_establecimientos_productivos_sexo.csv), published by the Ministry of Economy and the Ministry of Labour. It contains WGS84 coordinates rounded to 0.001 degrees, year, sector, and grouped employment per establishment. The rounding accounts for the regular grid visible in the source data. The source methodology states that employment is assigned to the establishment's registered workplace address and that the published data covers formal registered salaried employment.

`scripts/fetch_workplace_data.py` downloads the source; `scripts/prepare_workplaces.py` filters to 2022 and the AMBA bounding box, groups establishments sharing the same rounded source coordinate, and converts employment bands to destination capacities: `1–9 → 5`, `10–49 → 29.5`, `50–199 → 124.5`, `200–499 → 349.5`, and `500+ → 500` as a conservative lower-bound assumption.

The rounded coordinates are retained in the processed source for provenance, but they are not exported as demand points. During demand generation, each prepared workplace is assigned to its nearest census radio and then to that radio's adaptive display cluster. This removes false sub-block precision and gives residences and jobs the same spatial resolution without random coordinate jitter.

Demand first balances formal workplace capacity against scaled residence-based employed residents with a distance-constrained iterative proportional fitting model over internal 0.02-degree solver zones. A gravity-bounded maximum-flow pass identifies a feasible support, and a minimum-surprisal transportation solve projects the dense matrix onto exact flows while retaining quantized lower bounds from the dense reference. The zone flows are then disaggregated exactly to adaptive census clusters. The difference between total employed residents and formal workplace capacity is represented as local residual employment at residential origins because the source does not locate those jobs.

Exported job points use employed-resident-weighted adaptive census-cluster coordinates and may contain more than 200 jobs. Only individual population records are split to at most 200 people for game compatibility. Residence, workplace, and local-employment roles in the same cluster share one demand point.

## Existing local input

`argentina-latest.osm.pbf` is the current local OSM extract used by default for roads and geographic context. Replace it with a newer extract when rebuilding and record its source date here.

### Overture buildings

The build queries the latest Overture Maps building release directly for the configured bounding box. The v0.3.0 build applies Depot v1.2.3's 40 m² minimum footprint threshold before materialization, exports only geometry and height, then uses Depot's 1 m simplification, native indexes, and tile generation with an 8 GB Mapshaper cap. Multipart footprints are exploded before indexing so JSON and binary counts reconcile. OSM building tags are not substituted for this source.

The v0.3.1 compatibility release reuses the v0.3.0 OSM, Overture 2026-07-22.0, census, and workplace inputs. It rebuilds the basemap tile translation from the retained `bue-clean.mbtiles` with Depot 1.2.7, preserving the building and demand data while moving college, university, and school polygons into the game's commercial tile layer.

The v0.3.2 release changes only the map version and release metadata so the Registry can identify its Subway Builder compatibility range.

### CABA parcels and land use for v0.3.3

Official Buenos Aires City [cadastral parcel GeoJSON](https://data.buenosaires.gob.ar/es/dataset/parcelas) and [2022–2024 land-use survey CSV](https://data.buenosaires.gob.ar/es/dataset/relevamiento-usos-suelo), retrieved 2026-09-24:

- `caba_parcels.geojson`: `https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/parcelas/parcelas_catastrales.geojson`; SHA-256 `ed572c6b5bd6bf689ed602f14f4ed774259d096e79b76990cc32351e0020d3a7`.
- `caba_land_use.csv`: `https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/relevamiento-usos-suelo/relevamiento-usos-del-suelo-2022-2024.csv`; SHA-256 `5743336654ff9034a2f54129dd7c89011aa401c151828319b7fa1b06367fa2f1`.

The city data portal attributes both inputs to the Government of the City of Buenos Aires under a Creative Commons Attribution license; check each resource's current license terms when redistributing source files. The release ships only derived anchors, embedded as demand-point positions, not the source files.

`prepare_caba_anchors.py` joins normalized `SMP`/`smp` identifiers, selects active `RESIDENCIAL` survey records, and uses the maximum reported floor count per parcel as a relative placement weight. It computes a weighted representative point within each CABA census radio; if that mean falls outside the radio, it uses the heaviest parcel's representative point. Radios without a matched residential parcel use their original representative point. The survey describes observed parcel use and floors, not residents or jobs. Census employment totals and CEP XXI workplace capacities remain the model inputs.

The tile pipeline also maps OSM park and aerodrome polygons from Depot's `landuse` layer into Subway Builder 1.7.1's `parks` and `airports` layers. It computes the required numeric park `area` in square metres from the tile geometry. This fixes game visibility for those existing geographic polygons; the cadastral land-use survey is not treated as a complete park boundary inventory.
