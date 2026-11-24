# ADR-0005: Match stations with an in-memory index

## Status

Accepted

## Date

2026-11-24

## Context

Each request must find the stations within a few miles of a route and give each a position along it. A route can be 3,000 miles long with thousands of points. There are 6,626 stations, and they change only when the price file is imported again.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| PostGIS with `ST_DWithin` on the route line | Standard for spatial queries in Django (GeoDjango). | Needs PostgreSQL, PostGIS, GDAL and GEOS for a static table of 6,626 rows; a database round trip per request. |
| Brute force in Python | No dependencies. | Millions of distance computations per request. |
| k-d tree in memory, built per process (SciPy `cKDTree`) | Milliseconds per request; no extra service; SQLite stays the store. | Adds NumPy and SciPy; each process holds the stations, a few megabytes. |

## Decision

Load the stations once per process into `StationIndex`, which projects them onto a sphere of Earth's radius. For each route, densify the line so its points are at most half a mile apart, and build a k-d tree on them. Then query every station's nearest route point within the corridor. The nearest point's distance along the route, scaled to the provider's distance, is the mile marker.

## Consequences

- Matching the 2,776-mile recorded route, 15,822 points, takes 20 to 30 ms.
- Mile markers are accurate to a quarter of a mile.
- The index is immutable, so threads share it without locks. A new import needs a process restart to be seen.
- Moving to PostgreSQL later changes only the station loader.

## Related requirements

NFR-01, FUEL-01
