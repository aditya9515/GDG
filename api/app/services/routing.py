from __future__ import annotations

import math

import httpx

from app.core.config import Settings
from app.models.domain import GeoPoint, RouteSummary


def _distance_km(a: GeoPoint | None, b: GeoPoint | None) -> float | None:
    if a is None or b is None:
        return None
    radius = 6371.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlng = math.radians(b.lng - a.lng)
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(value))


class RoutingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def route(self, origin: GeoPoint | None, destination: GeoPoint | None) -> RouteSummary:
        fallback = self._fallback(origin, destination)
        if origin is None or destination is None or not self.settings.google_maps_api_key:
            return fallback

        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                "https://routes.googleapis.com/directions/v2:computeRoutes",
                params={"key": self.settings.google_maps_api_key},
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
                },
                json={
                    "origin": {"location": {"latLng": {"latitude": origin.lat, "longitude": origin.lng}}},
                    "destination": {"location": {"latLng": {"latitude": destination.lat, "longitude": destination.lng}}},
                    "travelMode": "DRIVE",
                    "routingPreference": "TRAFFIC_AWARE",
                },
            )
            response.raise_for_status()
            payload = response.json()
            routes = payload.get("routes", [])
            if not routes:
                return fallback
            route = routes[0]
            distance_km = round((route.get("distanceMeters", 0) or 0) / 1000, 2)
            duration_text = route.get("duration", "0s")
            duration_minutes = self._duration_to_minutes(duration_text)
            return RouteSummary(
                provider="google_routes",
                distance_km=distance_km,
                duration_minutes=duration_minutes,
                polyline=route.get("polyline", {}).get("encodedPolyline"),
            )

    def _fallback(self, origin: GeoPoint | None, destination: GeoPoint | None) -> RouteSummary:
        distance_km = _distance_km(origin, destination)
        duration_minutes = None if distance_km is None else max(8, int((distance_km / 35) * 60))
        return RouteSummary(provider="fallback", distance_km=distance_km, duration_minutes=duration_minutes)

    def _duration_to_minutes(self, value: str) -> int:
        raw = value.removesuffix("s")
        try:
            seconds = float(raw)
        except ValueError:
            return 0
        return max(1, int(seconds // 60))
