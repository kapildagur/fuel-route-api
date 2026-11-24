# fuel-route-api

A Django API that plans where a truck with a 500-mile range should buy diesel between two US locations, and returns the route, the stops and the total fuel cost.

Documentation: [design](docs/design.md) (requirements, architecture, test plan) and [decision records](docs/adr/README.md).

## Features

- **One request, one routing call.** `GET /api/v1/fuel-plan?start=Chicago, IL&finish=Dallas, TX` returns the route as GeoJSON, the fuel stops in driving order, and the totals. Towns and coordinates resolve locally, so the request calls [OpenRouteService](https://openrouteservice.org/) once; a street address costs one geocoding call per end. Repeated requests within an hour make no calls at all.
- **Lowest-cost plan, without pointless stops.** The planner finds the cheapest purchases for a 50-gallon tank at 10 miles per gallon, then drops any stop that saves less than $5. The response shows the lowest-cost plan's total beside the one returned, and `min_stop_saving=0` returns the lowest-cost plan itself.
- **Real prices, located offline.** All 6,626 US stations in the supplied OPIS price file are placed at their town from the US Census Bureau Gazetteer and GeoNames. No request geocodes a station.
- **A map in the browser.** Every response carries a `map_url` that opens a Leaflet map of the route and its numbered stops.
- **Lean responses.** The route line is simplified to within 50 m for display. New York to Los Angeles comes back in under 64 KB instead of about 340 KB, while stations are still matched against the full line.
- **Fast.** Matching stations to a 2,800-mile route and planning take about 40 ms. The routing call, 0.25 to 2.2 seconds in tests against the live API, takes most of the response time.
- **Shared cache when you need it.** Set `REDIS_URL` and every worker shares one Redis for routes, geocoding answers and the rate limit. If Redis goes down, requests still succeed through the provider.
- **Clear errors.** Every error is an RFC 9457 problem details response with a stable `code`. When a stretch of road has no station in range, the error names the mile where the fuel runs out.

## Status

Version 0.1.0, unreleased. The API and the response format may change before 1.0; see the [changelog](CHANGELOG.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and a free OpenRouteService API key: create an account at <https://account.heigit.org/signup>. The free plan allows 200 truck routes and 100 geocoding requests a day; repeated requests are served from the cache and do not count.

1. Create your settings file and put your key in `ORS_API_KEY`:

   ```bash
   cp .env.example .env
   ```

2. Install the dependencies, create the database and import the stations:

   ```bash
   uv sync
   make data
   ```

   The import prints `Imported 6626 stations; 0 left out without a known town.`

3. Start the server:

   ```bash
   make run
   ```

4. Ask for a plan:

   ```bash
   curl -G http://127.0.0.1:8000/api/v1/fuel-plan \
     --data-urlencode "start=Chicago, IL" \
     --data-urlencode "finish=Dallas, TX"
   ```

   Open the `map_url` from the response in a browser to see the route.

To run it in Docker instead, set `ORS_API_KEY` and `DJANGO_SECRET_KEY` in `.env`, then:

```bash
docker compose up --build
```

The image builds the station database while it builds, so the container serves on <http://localhost:8000> within a second of starting. Compose also starts Redis for the shared cache.

## Using the API

### Request

`GET /api/v1/fuel-plan`

| Parameter | Required | Default | Meaning |
| --- | --- | --- | --- |
| `start` | yes | | Where the trip begins: `City, ST`, `latitude,longitude`, or a street address. At most 200 characters. |
| `finish` | yes | | Where the trip ends, in the same forms. |
| `start_fuel_gallons` | no | `50` (a full tank) | Fuel in the tank at the start. |
| `min_stop_saving` | no | `5.00` | Drop a stop when skipping it costs less than this many dollars more. `0` returns the lowest-cost plan. |

### Response

An abridged response for Chicago to Dallas on the truck route, with the route line cut to two points:

```json
{
  "start": {"label": "Chicago, IL", "latitude": 41.837045,
            "longitude": -87.684939, "source": "place_directory"},
  "finish": {"label": "Dallas, TX", "latitude": 32.793333,
             "longitude": -96.766513, "source": "place_directory"},
  "route": {"distance_miles": 922.2, "duration_hours": 18.1},
  "vehicle": {"tank_gallons": 50.0, "miles_per_gallon": 10.0,
              "range_miles": 500.0, "start_fuel_gallons": 50.0},
  "fuel_stops": [
    {"station_id": 2231, "name": "QUIKTRIP #605",
     "address": "I-270, EXIT 33", "city": "Saint Louis", "state": "MO",
     "latitude": 38.635699, "longitude": -90.244582,
     "mile_marker": 294.3, "distance_from_route_miles": 1.3,
     "price_per_gallon": 2.899, "gallons": 29.429, "cost": 85.31},
    {"station_id": 64106, "name": "RAPID ROBERTS #122",
     "address": "SR-43", "city": "Joplin", "state": "MO",
     "latitude": 37.075218, "longitude": -94.501259,
     "mile_marker": 574.2, "distance_from_route_miles": 2.1,
     "price_per_gallon": 2.899, "gallons": 12.794, "cost": 37.09}
  ],
  "summary": {
    "fuel_stop_count": 2, "gallons_purchased": 42.223,
    "total_fuel_cost": 122.4, "currency": "USD",
    "min_stop_saving": 5.0,
    "lowest_cost_plan": {"fuel_stop_count": 2, "total_fuel_cost": 122.4},
    "fuel_used_gallons": 92.223, "arrival_fuel_gallons": 0.0,
    "stations_considered": 160
  },
  "map": {"type": "FeatureCollection", "features": ["..."]},
  "map_url": "http://localhost:8000/map/?start=Chicago%2C+IL&finish=Dallas%2C+TX"
}
```

`total_fuel_cost` is the sum of the stop costs, and each stop's `cost` is its `gallons` times its `price_per_gallon`, rounded to the cent. The truck starts with 50 gallons and buys 42.223, which together cover the 92.223 gallons the trip burns. `map` is a GeoJSON FeatureCollection with the route line, the start, the finish and one point per stop; paste it into any GeoJSON viewer.

### Errors

Errors use the `application/problem+json` format:

```json
{
  "type": "about:blank",
  "title": "No fuel within range",
  "status": 422,
  "detail": "The vehicle runs out of fuel at mile 50.0 and the next station is at mile 120.0.",
  "code": "unreachable_segment",
  "fuel_runs_out_at_mile": 50.0,
  "next_station_mile": 120.0
}
```

The [error table](docs/design.md#44-errors) lists every `code` and its status.

### Other endpoints

| Path | Returns |
| --- | --- |
| `/map/` | The map page; takes the same query parameters. |
| `/healthz` | `{"status": "ok", "stations": 6626}`, or 503 when no station is loaded. Never calls the provider. |
| `/api/schema/` | The OpenAPI 3 schema. |

### Postman

Import `postman/fuel-route-api.postman_collection.json` and set its `baseUrl` variable to your server. Each request has tests and a saved example response, so you can read the output before you run anything.

To run a batch of routes, open the Collection Runner, choose the "Data-driven" folder, and select `postman/routes.csv` as the data file. Each row of the file gives a start, a finish, the optional parameters, and the status the request should return.

## Database access

| When | Queries | How |
| --- | --- | --- |
| Server start | 1 | Every station, only the columns the matcher needs, into an in-memory index. |
| `City, ST` request | 1 per end | Unique index on `place (state, search_key)`; no sorting. |
| Coordinates, street address, health check | 0 | Answered from memory, the cache or the provider. |

Tests in `tests/integration/test_database_access.py` pin these counts and check the query plan.

## Assumptions

- The truck starts with a full tank unless `start_fuel_gallons` says otherwise, and the cost counts only fuel bought on the way. It arrives with an empty tank.
- A station stands at its town's point, and only stations within 5 miles of the route are considered. The short detour to a station is not counted.
- Where the price file lists a station more than once, its lowest price applies. Canadian stations are left out.

The [design](docs/design.md#23-assumptions) explains each assumption and its effect.

## Configuration

Settings come from the environment or from `.env`; [.env.example](.env.example) lists them all.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ORS_API_KEY` | none, required | OpenRouteService API key. |
| `DJANGO_SECRET_KEY` | none; required unless `DJANGO_DEBUG=true` | Django secret key. |
| `DJANGO_DEBUG` | `false` | Debug mode, for local use only. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host names the server answers to. |
| `ORS_PROFILE` | `driving-hgv` | OpenRouteService routing profile. |
| `ORS_TIMEOUT_SECONDS` | `10` | Timeout of each provider call. |
| `FUELROUTE_TANK_GALLONS` | `50` | Tank size. |
| `FUELROUTE_MILES_PER_GALLON` | `10` | Fuel economy. |
| `FUELROUTE_CORRIDOR_MILES` | `5` | How far from the route a station may be. |
| `FUELROUTE_MIN_STOP_SAVING` | `5` | Default for `min_stop_saving`, in dollars. |
| `FUELROUTE_MAP_TOLERANCE_METERS` | `50` | How far the route line in a response may stray from the full line; `0` returns the full line. |
| `FUELROUTE_CACHE_SECONDS` | `3600` | How long routes and geocoding answers are cached. |
| `FUELROUTE_RATE_LIMIT` | `60/minute` | Requests allowed per client address. |
| `REDIS_URL` | none (per-process memory) | Redis for the shared cache and rate limit, for example `redis://localhost:6379/0`. |
| `DATABASE_PATH` | `var/fuelroute.sqlite3` | SQLite database file. |

## Data

`data/fuel-prices.csv` is the OPIS truck stop price file. `data/places.csv` gives towns their coordinates and is built from the US Census Bureau Gazetteer (public domain) and [GeoNames](https://www.geonames.org/) (CC BY 4.0). [data/README.md](data/README.md) describes each file and how to rebuild it. The map page shows tiles from OpenStreetMap; the map data is copyright OpenStreetMap contributors.

## Development

```bash
make dev        # install dependencies and git hooks
make check      # lint, layering, security and strict type checks
make test-all   # unit, integration and end-to-end tests with coverage
make bench      # the planning speed budget
```

[CONTRIBUTING.md](CONTRIBUTING.md) lists every command and the commit rules.

## Contributing and security

Contributions are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md) first. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License

MIT; see [LICENSE](LICENSE).
