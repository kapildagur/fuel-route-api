# ADR-0008: Store data in PostgreSQL in production and SQLite in development

## Status

Accepted

## Date

2026-11-24

## Context

The station and place tables are written only by `import_stations` and read at start-up and once per `City, ST` query (NFR-09). SQLite serves that load, but the target deployment runs its Django services on PostgreSQL, several containers may share one database, and a container's file system is read-only (`compose.yaml`). A reviewer or contributor should still be able to run the project without a database server.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| SQLite only | No server; the image carries its own database. | One file per container; no shared, managed database. |
| PostgreSQL only | One engine everywhere. | Every checkout and every test run needs a database server. |
| PostgreSQL through `DATABASE_URL`, SQLite otherwise | Production gets a shared, managed database; a checkout runs as it is. | Two engines to keep working, so both are tested. |

## Decision

When `DATABASE_URL` holds a `postgres://` or `postgresql://` URL, Django uses PostgreSQL through psycopg 3, parsed by `dj-database-url`, with connections kept for 60 seconds and health-checked before reuse. Otherwise it uses the SQLite file at `DATABASE_PATH`. Any other URL scheme stops the process at start-up. `compose.yaml` runs PostgreSQL 18 with a one-off `setup` service that migrates and imports before the API starts.

## Consequences

- The schema stays portable: the unique constraint on `place (state, search_key)` serves the town lookup on both engines, which `test_town_lookup_is_served_by_the_unique_index` checks against each engine's query plan.
- `make test-postgres` and the CI job "Tests on PostgreSQL" run the unit and integration tests on a real PostgreSQL 18 started by Testcontainers.
- The Docker image still builds a SQLite database, so it also runs on its own without `DATABASE_URL`.
- The station index stays in memory (ADR-0005); PostgreSQL holds the data, not the spatial query.

## Related requirements

DATA-02, NFR-09, NFR-10
