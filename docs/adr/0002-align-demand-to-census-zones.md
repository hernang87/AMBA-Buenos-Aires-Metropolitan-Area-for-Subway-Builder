# ADR-0002: Align Residence and Workplace Demand to Census-Derived Zones

## Status

Accepted

## Context

The CEP XXI/SIPA workplace source rounds every coordinate to 0.001 degrees. ADR-0001 retained all 69,749 unique published coordinates, which removed overlapping points but exposed the rounding lattice in the game. It also represented workplaces at a much finer apparent resolution than residences, even though the workplace coordinates do not support sub-block precision.

The model must preserve the 7,794,695 employed-resident total, formal workplace capacity, exact gravity marginals, individual populations no larger than 200, and acceptable commute-distance drift. It must also remain deterministic and practical to rebuild.

## Decision

Use the existing 0.02-degree census-derived residence zones as the common spatial layer:

1. Build each zone location as the employed-resident-weighted mean of its census-radio representative points.
2. Assign each prepared workplace coordinate to its nearest zone using a latitude-adjusted spatial index.
3. Sum formal workplace capacity by zone before gravity balancing.
4. Balance and sparsify flows between the common zone locations.
5. Emit one canonical point per zone for both residence and workplace roles.

The processed workplace file retains rounded source coordinates for provenance. No random jitter is introduced.

## Consequences

### Positive

- Removes the visually misleading 0.001-degree workplace lattice.
- Gives residence and workplace demand the same spatial resolution.
- Reduces point count and game rendering overhead.
- Preserves source totals and deterministic builds.
- Keeps exact-coordinate merging automatic because both roles share zone locations.

### Negative

- Workplace locations are generalized to roughly 0.02 degrees.
- Short trips may shift within a zone.
- Nearest-zone assignment is an approximation rather than point-in-polygon assignment.

### Neutral

- The gravity model remains synthetic rather than observed origin-destination data.
- Local residual employment remains at residence zones.

## Alternatives Considered

- **Keep rounded source coordinates:** rejected because it displays the source anonymization lattice as false precision.
- **Add random jitter:** rejected because it invents unsupported locations and makes builds harder to reproduce.
- **Use all 18,018 census radios as gravity nodes:** rejected because the candidate graph and exact transport solve become unnecessarily large for the game’s useful resolution.
- **Use regular workplace centroids:** rejected because a second grid would retain the visual mismatch.

## References

- Registry feedback: <https://github.com/Subway-Builder-Modded/registry/issues/5311#issuecomment-5053371835>
- CEP XXI/SIPA methodology: <https://cdn.produccion.gob.ar/cdn-cep/establecimientos-productivos/Metodologia_establecimiento_productivos.pdf>
