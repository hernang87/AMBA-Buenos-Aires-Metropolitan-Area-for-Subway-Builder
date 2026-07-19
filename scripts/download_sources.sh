#!/usr/bin/env sh
set -eu

mkdir -p data/raw
url='https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=geonode:radios_censales2&outputFormat=application/json'
curl -fL "$url" -o data/raw/rmba_areas.geojson
printf '%s\n' 'Downloaded census-area geometry.'
printf '%s\n' 'Save matching INDEC Census 2022 statistics as data/raw/rmba_stats.csv.'
printf '%s\n' 'Run scripts/fetch_workplace_data.py to download workplace locations and employment bands.'
