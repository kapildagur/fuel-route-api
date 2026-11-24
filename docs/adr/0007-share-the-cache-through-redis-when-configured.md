# ADR-0007: Share the cache through Redis when configured

## Status

Accepted

## Date

2026-11-24

## Context

ADR-0006 caches routes and geocoding answers in Django's local-memory cache. Each worker process keeps its own copy, so with four gunicorn workers the same route can cost four provider calls, and the rate limit counts each worker separately. The free OpenRouteService plan allows 200 truck routes a day (OI-07), so duplicate calls matter.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Keep the local-memory cache | No extra service. | One cache and one rate-limit counter per process. |
| Django's built-in Redis cache backend | Shared by every worker and host; no extra Django package; Redis evicts by memory. | One more service to run; the cache can be unavailable. |
| Database cache table | Uses the existing database. | Turns every cache read into a database query, against NFR-09. |

## Decision

When `REDIS_URL` is set, both caches (`default` for rate-limit counters, `routes` for routes and geocoding answers) use `django.core.cache.backends.redis.RedisCache`, each with its own key prefix. Without it, the local-memory cache stays the default, so a development checkout needs no Redis. Redis calls time out after half a second.

A failing cache never fails a request: `CachedRoutingProvider` and `CachedGeocoder` treat a store error as a miss, and `FailOpenAnonRateThrottle` lets the request through. Routes are stored as packed doubles, 247 KB for the cross-country route instead of 433 KB pickled, which helps both backends.

## Consequences

- Every worker shares one cache and one rate limit; `compose.yaml` runs Redis with a 128 MB limit and least-recently-used eviction.
- A Redis outage raises provider calls and suspends rate limiting until Redis returns; both are logged as warnings.
- Integration tests run against a real Redis started by Testcontainers, and skip when Docker is not available.

## Related requirements

NFR-02, NFR-05, OI-04, OI-07
