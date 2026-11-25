# Test fixtures

| File | Holds |
| --- | --- |
| `route-chicago-dallas.json` | The OpenRouteService response for downtown Chicago to downtown Dallas: 968.3 miles, 4,385 points. |
| `route-new-york-los-angeles.json` | The OpenRouteService response for New York City to Los Angeles: 2,775.6 miles, 15,822 points. |

Both were recorded on 2026-11-24 from `POST /v2/directions/driving-hgv/geojson` on `api.openrouteservice.org`, with `geometry_simplify` on and instructions off, the request this service sends. On 2026-11-25 the same request to `api.heigit.org/openrouteservice/v2/directions/driving-hgv/geojson` returned the same Chicago to Dallas route. Route data copyright OpenStreetMap contributors (ODbL), routed by openrouteservice.org.

The end-to-end tests serve the Chicago to Dallas file from a fake OpenRouteService; the benchmark plans the New York to Los Angeles file.
