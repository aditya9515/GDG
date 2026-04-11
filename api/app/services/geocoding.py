from __future__ import annotations

import httpx

from app.core.config import Settings
from app.models.domain import GeoPoint


KNOWN_LOCATIONS = {
    "shantinagar bridge": GeoPoint(lat=22.5726, lng=88.3639),
    "district hospital": GeoPoint(lat=28.6139, lng=77.2090),
    "market road": GeoPoint(lat=19.0760, lng=72.8777),
    "hillview colony (road blocked by landslide)": GeoPoint(lat=30.3165, lng=78.0322),
}


class GeocodingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def geocode(self, location_text: str) -> GeoPoint | None:
        if not location_text or len(location_text.strip()) < 4:
            return None

        known = KNOWN_LOCATIONS.get(location_text.lower().strip())
        if known:
            return known

        if not self.settings.google_maps_api_key:
            return None

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": location_text, "key": self.settings.google_maps_api_key},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("results"):
                return None
            location = payload["results"][0]["geometry"]["location"]
            return GeoPoint(lat=location["lat"], lng=location["lng"])
