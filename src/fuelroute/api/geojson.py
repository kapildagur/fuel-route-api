"""GeoJSON (RFC 7946) rendering of a fuel plan: the route line and its points."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fuelroute.core.simplify import simplify_path

if TYPE_CHECKING:
    from fuelroute.core.geo import Coordinate
    from fuelroute.core.service import FuelPlan

__all__ = ["fuel_plan_feature_collection"]

_DECIMALS = 5
"""Five decimal places of a degree is about a metre, finer than any input here."""


def fuel_plan_feature_collection(plan: FuelPlan, *, tolerance_meters: float) -> dict[str, Any]:
    """Return a FeatureCollection with the route, the start, the finish and each stop.

    The route line is simplified to within ``tolerance_meters`` of the full line, which
    keeps a cross-country response near 50 KB instead of several hundred.
    """
    line = simplify_path(plan.route.path, tolerance_meters=tolerance_meters)
    features: list[dict[str, Any]] = [
        _feature(
            {
                "type": "LineString",
                "coordinates": [_position(point) for point in line],
            },
            kind="route",
            distance_miles=round(plan.route.distance_miles, 1),
            tolerance_meters=tolerance_meters,
        ),
        _point(plan.start.coordinate, kind="start", label=plan.start.label),
        _point(plan.finish.coordinate, kind="finish", label=plan.finish.label),
    ]
    for sequence, stop in enumerate(plan.stops, start=1):
        station = stop.station_on_route.station
        features.append(
            _point(
                station.location,
                kind="fuel_stop",
                sequence=sequence,
                station_id=station.station_id,
                name=station.name,
                address=station.address,
                city=station.city,
                state=station.state,
                mile_marker=round(stop.station_on_route.mile_marker, 1),
                price_per_gallon=float(station.price_per_gallon),
                gallons=float(stop.gallons),
                cost=float(stop.cost),
            )
        )
    return {"type": "FeatureCollection", "features": features}


def _point(coordinate: Coordinate, **properties: Any) -> dict[str, Any]:  # noqa: ANN401  # GeoJSON properties are free-form
    return _feature({"type": "Point", "coordinates": _position(coordinate)}, **properties)


def _feature(geometry: dict[str, Any], **properties: Any) -> dict[str, Any]:  # noqa: ANN401  # GeoJSON properties are free-form
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _position(coordinate: Coordinate) -> list[float]:
    return [round(coordinate.longitude, _DECIMALS), round(coordinate.latitude, _DECIMALS)]
