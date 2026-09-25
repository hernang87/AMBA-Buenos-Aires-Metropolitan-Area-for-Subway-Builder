#!/usr/bin/env sh
set -eu

mkdir -p data/raw
url='https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=geonode:radios_censales2&outputFormat=application/json'
curl -fL "$url" -o data/raw/rmba_areas.geojson
curl -fL 'https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/parcelas/parcelas_catastrales.geojson' -o data/raw/caba_parcels.geojson
curl -fL 'https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/relevamiento-usos-suelo/relevamiento-usos-del-suelo-2022-2024.csv' -o data/raw/caba_land_use.csv
printf '%s\n' 'Downloaded census-area geometry.'
printf '%s\n' 'Save matching INDEC Census 2022 statistics as data/raw/rmba_stats.csv.'
printf '%s\n' 'Run scripts/fetch_workplace_data.py to download workplace locations and employment bands.'
printf '%s\n' 'Run scripts/prepare_caba_anchors.py after preparing census areas.'
