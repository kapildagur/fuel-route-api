# ADR-0004: Drop stops that save less than a threshold

## Status

Accepted

## Date

2026-11-24

## Context

The brief says the optimal location "mostly means cost effective". The plan that is cheapest to the cent stops wherever a slightly cheaper station is near. On the recorded New York to Los Angeles route it makes 14 stops, some for one gallon. A driver loses more in time at such a stop than the few cents it saves.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Return the cheapest plan only | Exact and simple. | Impractical stops. |
| Exact plan with a fixed cost per stop | Optimal for cost plus stops. | Needs a dynamic program; slow in Python. |
| Drop stops from the cheapest plan while each saves less than a threshold | Short; bounded extra cost; reuses the exact planner. | A heuristic: does not promise the fewest stops. |

## Decision

After the greedy plan, try removing each stop's station, smallest purchase first. Keep the plan without it when that plan has fewer stops and costs less than `min_stop_saving` more per stop removed. Repeat until no removal qualifies. The threshold defaults to $5 (`FUELROUTE_MIN_STOP_SAVING`) and a request can override it; `min_stop_saving=0` returns the cheapest plan. The response reports the cheapest plan's cost and stop count beside the returned plan.

## Consequences

- New York to Los Angeles drops from 14 stops to 11 for $0.96 more; Chicago to Dallas from 4 to 2 for $0.72 more.
- The extra cost never exceeds the threshold times the stops removed; a property-based test checks this and that every plan stays feasible.
- The pass runs the planner about 30 times on a cross-country route, about 25 ms.

## Related requirements

FUEL-05, NFR-01
