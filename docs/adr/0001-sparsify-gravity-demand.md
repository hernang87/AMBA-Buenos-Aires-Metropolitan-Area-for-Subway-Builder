# ADR-0001: Project Gravity Demand onto Sparse Exact Flows

## Status

Accepted

## Context

The v0.2.3 AMBA demand model preserved formal workplace capacity and capped every population at 200, but it emitted 1,072,215 population records with a median size of 2. It also split workplace capacity into multiple points at identical coordinates. The resulting archive was unstable in Subway Builder and displayed z-fighting in the demand view.

The source contains 69,749 unique AMBA workplace coordinates rounded to 0.001 degrees. These locations should remain visible at their published resolution. The 7,794,695 employed-resident total, 4,127,148 formal-workplace total, and 12 km gravity behavior must remain reconciled.

Candidate-graph feasibility tests showed that 16 through 256 candidate origins per workplace cell cannot carry all formal capacity. The existing 320-candidate graph is feasible, so sparsity must be introduced after balancing rather than by dropping candidates beforehand.

## Decision

Keep the dense doubly constrained gravity calculation on the feasible 320-candidate graph, then project it onto a sparse exact transportation solution:

1. Iterative proportional fitting produces the gravity-weighted reference matrix.
2. Edge capacities equal to sixteen times the reference flow identify a feasible reduced support with maximum flow.
3. A HiGHS transportation solve minimizes the negative log of the reference-flow probability on that support.
4. Exact integer origin and workplace-cell marginals are required.
5. Cell flows are allocated deterministically to native workplace coordinates.

Each exact coordinate has one canonical point. Points have no artificial capacity limit; only individual population records are capped at 200. Generation fails above 250,000 populations.

## Consequences

### Positive

- Preserves all employed-resident and workplace-capacity totals.
- Retains the intent and commute distances of the gravity model.
- Keeps native workplace locations without overlapping point records.
- Reduces demand cardinality and packaged file size substantially.
- Produces deterministic diagnostics and hard release gates.

### Negative

- Adds SciPy/HiGHS as a direct build dependency.
- The full AMBA optimization takes several minutes.
- The sparse solution is one modeled projection, not an observed OD matrix.

### Neutral

- Source-coordinate rounding remains visible as a regular grid.
- Local residual employment continues to represent jobs absent from the formal workplace source.

## Alternatives Considered

- **Lower the candidate-origin count:** rejected because graphs through 256 candidates are infeasible for the exact marginals.
- **Merge points without changing flows:** rejected because it leaves approximately one million mostly tiny populations.
- **Export 0.005-degree workplace centroids:** rejected because it discards native source-location fidelity.
- **Use arbitrary maximum flow:** rejected because it increased mean commute distance and weakened the gravity interpretation.
- **Solve the full 3.2-million-variable transportation LP:** rejected because its rebuild time was impractical.

## References

- Registry feedback: <https://github.com/Subway-Builder-Modded/registry/issues/5311#issuecomment-5053371835>
- CEP XXI/SIPA methodology: <https://cdn.produccion.gob.ar/cdn-cep/establecimientos-productivos/Metodologia_establecimiento_productivos.pdf>
