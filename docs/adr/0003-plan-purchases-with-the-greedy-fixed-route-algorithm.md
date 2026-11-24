# ADR-0003: Plan purchases with the greedy fixed-route algorithm

## Status

Accepted

## Date

2026-11-24

## Context

When the route is known, the stations along it form a line of mile markers with prices. The vehicle holds 50 gallons and burns one gallon every 10 miles. The plan must reach the finish, never run dry, never overfill, and cost as little as possible.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Fill up whenever the tank would not reach the next station | Trivial. | Ignores prices; can cost far more than needed. |
| Dynamic program over stations and fuel levels | Exact; extends to per-stop costs. | Fuel must be discretised; slow in Python for hundreds of stations. |
| Greedy rule for a fixed route (Khuller, Malekian and Mestre, 2011) | Exact for this problem; linear time apart from a window scan; short to read. | Gives the lowest cost only, with no notion of stop count. |

## Decision

Use the greedy rule. At each station, if a cheaper station lies within a full tank's range, buy exactly enough to reach the first one. Otherwise fill the tank and go to the cheapest station within range, preferring the farthest on a tie. The finish counts as the cheapest point, so the truck arrives empty. The start is not a station: the truck drives to the first station on its starting fuel.

## Consequences

- The plan is the cheapest possible for the stations in the corridor. A property-based test compares it with an exact dynamic program on random trips.
- A stretch longer than the range raises `UnreachableSegmentError` with the mile where the fuel runs out.
- The cheapest plan can include top-ups of a gallon that save cents; ADR-0004 handles them.
- Planning takes about 1 ms for 350 stations.

## Related requirements

FUEL-01, FUEL-02, FUEL-04, FUEL-06, NFR-01
