# Test fixtures

| File | Holds |
| --- | --- |
| `route-chicago-dallas.json` | A 966.9-mile driving route in the OpenRouteService GeoJSON directions format, 424 points. |
| `route-new-york-los-angeles.json` | A 2,794.2-mile driving route in the same format, 1,742 points. |

The geometry comes from OpenStreetMap data (copyright OpenStreetMap contributors, ODbL) routed by the OSRM demo server, simplified to about 100 m and rounded to five decimal places. The end-to-end tests serve the Chicago to Dallas file from a fake OpenRouteService; the benchmark plans the New York to Los Angeles file.
