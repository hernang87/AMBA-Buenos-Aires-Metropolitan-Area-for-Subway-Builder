# ADR-0003: Export Adaptive Census Clusters

## Status

Accepted

## Context

ADR-0002 mapped both residence and workplace demand onto 1,502 census-derived 0.02-degree zones. This removed the workplace source's 0.001-degree lattice, but exporting one weighted point per fixed solver cell exposed a coarser rectangular lattice.

The display needs to follow the real metropolitan footprint without returning to the unstable million-population output. Gravity balancing must remain exact, deterministic, and practical to rebuild.

## Decision

Separate solver geography from display geography:

1. Retain the 1,502 regular zones only for gravity balancing.
2. Allocate exactly 6,000 display clusters among those zones according to employed residents, with at least one cluster per zone and no more clusters than census radios.
3. Apply deterministic Ward clustering to latitude-adjusted census-radio representative points within each solver zone.
4. Place each display point at the employed-resident-weighted centroid of its member radios.
5. Assign workplace capacity through the nearest census radio to its display cluster.
6. Preserve quantized lower bounds from the dense gravity matrix, solve the remaining exact sparse transport, and disaggregate each zone flow to origin and destination clusters with two deterministic transportation passes.

The release validator requires exactly 6,000 unique points, no more than 100,000 populations, individual populations no larger than 200, exact totals, and absolute mean/p90 commute drift no greater than 2/5 km.

## Consequences

### Positive

- Removes the visible one-point-per-cell lattice.
- Follows the density and shape of the census geography.
- Keeps the expensive gravity solve at 1,502 origins.
- Preserves exact origin, destination, and employment totals.
- Keeps output safely below the unstable million-population revision.

### Negative

- Display clusters cannot cross internal solver-zone boundaries.
- Ward clustering is spatial rather than administrative.
- Quantized dense-flow lower bounds increase population records compared with an unconstrained minimum-cost projection.

### Neutral

- The model remains synthetic rather than an observed origin-destination matrix.
- Workplace and residence coordinates have the same adaptive resolution.

## Alternatives Considered

- **Export every census radio:** rejected because 18,018 points add detail that is not necessary for the game.
- **Keep one point per solver cell:** rejected because the regular lattice remains visible.
- **Randomly jitter solver points:** rejected because it invents unsupported locations.
- **Use unconstrained sparse minimum cost:** rejected because it shortened mean commutes by more than four kilometres.

## References

- Registry feedback: <https://github.com/Subway-Builder-Modded/registry/issues/5311#issuecomment-5053371835>
- CEP XXI/SIPA methodology: <https://cdn.produccion.gob.ar/cdn-cep/establecimientos-productivos/Metodologia_establecimiento_productivos.pdf>
