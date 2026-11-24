# ADR-0002: Locate stations offline from public gazetteers

## Status

Accepted

## Date

2026-11-24

## Context

The price file gives each station an address such as "I-44, EXIT 283 & US-69", a city and a state, but no coordinates. Matching stations to a route needs a point for each. There are 6,626 US stations in 3,808 distinct towns. Geocoding them during a request is out of the question: it would cost thousands of calls.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Batch-geocode every address through a provider | Could place a station at its exit. | Thousands of calls against the daily geocoding quota; interstate exit strings geocode poorly; results depend on the provider. |
| Town coordinates from public gazetteers, built offline | No calls; reproducible; public data. | A station sits at its town's point, a few miles from its exit. |
| Exit coordinates from OpenStreetMap motorway junctions | Places stations at their exits. | Parsing exit numbers and road names from free text; much more work for 0.1.0. |

## Decision

Build `data/places.csv` once with `manage.py build_places`, from the US Census Bureau Gazetteer (places and county subdivisions, 2025) and GeoNames populated places, plus a short hand-checked alias file. The match uses `place_key`, which ignores case, punctuation and spacing and expands abbreviations such as "St." and "Ft.". The file is committed, so neither the import nor the server downloads anything.

## Consequences

- All 6,626 US stations receive coordinates: 3,585 towns from Census places, 92 from county subdivisions, 133 from GeoNames and 3 from the alias file.
- Station positions are accurate to the town, so the corridor is 5 miles wide by default. A station in a large city can fall outside it (OI-01).
- GeoNames data is licensed CC BY 4.0, so `data/README.md` and the README credit it.
- Rebuilding the file needs about 80 MB of downloads; `make places` does it.

## Related requirements

DATA-01, RTE-04, C-03
