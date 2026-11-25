# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

- `GET /api/v1/fuel-plan` returns the route between two US locations, the fuel stops that make the trip cheapest for a truck with a 500-mile range, and the total fuel cost.
- Locations can be `City, ST`, `latitude,longitude` or a street address. Towns and coordinates resolve without a provider call.
- `start_fuel_gallons` sets the fuel at the start; the default is a full tank.
- `min_stop_saving` drops stops that save less than the given dollars, $5 by default. The response reports the lowest-cost plan's total and stop count beside the plan returned.
- A GeoJSON map in every response, and a map page at `/map/` that draws it with Leaflet. The route line is simplified to within `FUELROUTE_MAP_TOLERANCE_METERS` (50 m by default), so a cross-country response stays under 64 KB.
- RFC 9457 problem details for every error, including the mile where the fuel runs out when no station is within range.
- `/healthz` and the OpenAPI schema at `/api/schema/`.
- `manage.py import_stations` loads the 6,626 US stations of the OPIS price file, and `manage.py build_places` rebuilds the town coordinates from the Census Bureau Gazetteer and GeoNames.
- Routes and geocoding answers are cached for an hour, so a repeated request makes no provider call.
- `DATABASE_URL` stores the data in PostgreSQL; without it the project runs on SQLite.
- `REDIS_URL` moves the route cache and the rate limit to a shared Redis. A Redis outage does not fail requests.
- A Docker image with the station database built in, and `compose.yaml` that runs the API with PostgreSQL and Redis.
- A Postman collection with tests and saved example responses, and `postman/routes.csv` to run a batch of routes in the Collection Runner.

### Changed

- OpenRouteService is called at `api.heigit.org`, because `api.openrouteservice.org` answers `410 Gone` since 2026-11-24. `ORS_BASE_URL` sets another host.
- The container runs gunicorn without its control socket, which the service does not use and the read-only file system cannot hold. gunicorn 25.1 or later is required.
