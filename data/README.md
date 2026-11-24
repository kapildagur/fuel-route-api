# Data files

| File | Rows | Source | License |
| --- | --- | --- | --- |
| `fuel-prices.csv` | 8,151 | OPIS truck stop retail diesel prices, supplied with the project brief. | Supplied with the brief; redistribution terms not stated. |
| `places.csv` | 32,072 | Built by `manage.py build_places` from the sources below. | Census rows: public domain. GeoNames rows: CC BY 4.0. |
| `place-aliases.csv` | 3 | Hand-checked coordinates for station towns no source names. | Coordinates taken from the Census Gazetteer. |

## fuel-prices.csv

Columns: `OPIS Truckstop ID`, `Truckstop Name`, `Address`, `City`, `State`, `Rack ID`, `Retail Price` (US dollars per gallon). The file has no coordinates. It holds 620 rows for Canadian provinces, which the import leaves out, and 905 rows that repeat a station ID with another price; the import keeps the lowest.

## places.csv

Columns: `name`, `state`, `latitude`, `longitude`, `source`. Each row is one town, keyed by its name and USPS state code. `source` is one of:

| Value | Dataset |
| --- | --- |
| `census_place` | US Census Bureau, 2025 Gazetteer Files, places. |
| `census_county_subdivision` | US Census Bureau, 2025 Gazetteer Files, county subdivisions; used for New England and New Jersey towns. |
| `geonames` | [GeoNames](https://www.geonames.org/) US dump, populated places (feature class P), the most populous where a name repeats in a state. |
| `alias` | `place-aliases.csv`. |

The file holds every Census place, so `City, ST` queries resolve for any US town, plus a row for each station town that only another source knows.

To rebuild it, run `make places`. It downloads about 80 MB into `.tmp/downloads` and writes the file sorted by state and name, so an unchanged source gives an unchanged file.

## Attribution

Town coordinates include data from GeoNames, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The US Census Bureau Gazetteer Files are in the public domain.
