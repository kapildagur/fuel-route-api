# ADR-0001: Use OpenRouteService for routing and geocoding

## Status

Accepted

## Date

2026-11-24

## Context

The brief asks for a free map and routing API, called once per request if possible and at most three times. The service needs a driving route between two US points, with its geometry and length, and a way to turn a street address into a point. The vehicle is a truck, so a route that respects truck restrictions is better than a car route.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| OpenRouteService hosted API | Free key; a heavy goods vehicle profile (`driving-hgv`); geocoding from the same key; GeoJSON output. | Needs a key; daily quotas; routes capped at 6,000 km. |
| OSRM public demo server | No key; fast. | A demo with no uptime promise and a usage policy against regular use; car profile only; no geocoding. |
| Google Maps Platform | Mature and accurate. | Needs a billing account, so it is not free to run. |

## Decision

Use the OpenRouteService directions endpoint with the `driving-hgv` profile, `geometry_simplify` on and turn-by-turn instructions off, and its geocode search endpoint restricted to the USA. The profile is a setting (`ORS_PROFILE`), so `driving-car` can replace it without code changes. The client sits behind the `RoutingProvider` and `Geocoder` ports, so another provider needs only a new adapter.

## Consequences

- Reviewers and operators need a free OpenRouteService key; the server refuses to start without one.
- A route longer than 6,000 km (3,728 miles) fails with `route_too_long`. Only corner-to-corner trips, such as Key West to northwest Washington, come near that length.
- Each provider call has a timeout and one retry for transient failures (NFR-03).
- The simplified geometry is accurate to tens of metres, well inside the 5-mile corridor, and keeps responses and cache entries small.

## Related requirements

RTE-01, RTE-02, C-02, C-04, NFR-02, NFR-03
