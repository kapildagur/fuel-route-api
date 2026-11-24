# ADR-0006: Resolve towns locally and cache provider answers

## Status

Accepted

## Date

2026-11-24

## Context

A request that geocodes both ends and then routes makes three provider calls, the most the brief accepts. Most callers name towns, such as "Chicago, IL", and the same pairs are asked again and again, for example by the map page right after the JSON request.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Always geocode through the provider | One code path. | Three calls per request; quota spent on towns the service already knows. |
| Accept coordinates only | One call. | Unfriendly for a demo or a dispatcher. |
| Resolve `City, ST` from the local place table, geocode only free text, cache both | One call for towns or coordinates, three at most for addresses, none on a repeat. | Two code paths; the cache is per process. |

## Decision

`FuelPlanService.resolve` reads coordinates directly, looks `City, ST` up in the place table, and sends only other text to the geocoder. `CachedRoutingProvider` and `CachedGeocoder` keep routes and answers, including "not found", in Django's cache for `FUELROUTE_CACHE_SECONDS` (one hour). Route keys round coordinates to five decimal places, about a metre; geocode keys hash the normalised text.

## Consequences

- A request between two towns makes exactly one provider call; a repeat makes none (NFR-02).
- The map page costs no extra provider call, because it fetches the same JSON within the cache lifetime.
- The cache is bounded to 256 entries, because request input decides the keys.
- Several worker processes each cache separately; a shared Redis cache fixes that (OI-04).

## Related requirements

RTE-01, RTE-04, C-04, NFR-02
