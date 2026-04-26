from __future__ import annotations

import re

import httpx

from app.core.config import Settings
from app.models.domain import GeocodeCacheEntry, GeoPoint, LocationConfidence
from app.repositories.base import Repository


KNOWN_LOCATIONS = {
    "shantinagar bridge": GeoPoint(lat=22.5726, lng=88.3639),
    "district hospital": GeoPoint(lat=28.6139, lng=77.2090),
    "market road": GeoPoint(lat=19.0760, lng=72.8777),
    "hillview colony (road blocked by landslide)": GeoPoint(lat=30.3165, lng=78.0322),
}


class GeocodingService:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository

    def _cache_key(self, location_text: str) -> str:
        normalized = re.sub(r"\s+", " ", location_text.strip().lower())
        normalized = re.sub(r"[^a-z0-9 ,.-]", "", normalized)
        return normalized

    async def geocode(self, location_text: str) -> GeoPoint | None:
        if not location_text or len(location_text.strip()) < 4:
            return None

        cache_key = self._cache_key(location_text)
        cached = self.repository.get_geocode_cache(cache_key)
        if cached is not None:
            return cached.geo

        known = KNOWN_LOCATIONS.get(location_text.lower().strip())
        if known:
            self.repository.save_geocode_cache(
                GeocodeCacheEntry(
                    cache_key=cache_key,
                    query_text=location_text,
                    formatted_address=location_text,
                    geo=known,
                    provider="seeded_known_location",
                    location_confidence=LocationConfidence.EXACT,
                )
            )
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
            result = payload["results"][0]
            location = result["geometry"]["location"]
            point = GeoPoint(lat=location["lat"], lng=location["lng"])
            self.repository.save_geocode_cache(
                GeocodeCacheEntry(
                    cache_key=cache_key,
                    query_text=location_text,
                    formatted_address=result.get("formatted_address", location_text),
                    geo=point,
                    provider="google_geocoding",
                    location_confidence=LocationConfidence.APPROXIMATE,
                )
            )
            return point

    def geocode_sync(self, location_text: str) -> GeoPoint | None:
        if not location_text or len(location_text.strip()) < 4:
            return None

        cache_key = self._cache_key(location_text)
        cached = self.repository.get_geocode_cache(cache_key)
        if cached is not None:
            return cached.geo

        known = KNOWN_LOCATIONS.get(location_text.lower().strip())
        if known:
            self.repository.save_geocode_cache(
                GeocodeCacheEntry(
                    cache_key=cache_key,
                    query_text=location_text,
                    formatted_address=location_text,
                    geo=known,
                    provider="seeded_known_location",
                    location_confidence=LocationConfidence.EXACT,
                )
            )
            return known

        if not self.settings.google_maps_api_key:
            return None

        with httpx.Client(timeout=10) as client:
            response = client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": location_text, "key": self.settings.google_maps_api_key},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("results"):
                return None
            result = payload["results"][0]
            location = result["geometry"]["location"]
            point = GeoPoint(lat=location["lat"], lng=location["lng"])
            self.repository.save_geocode_cache(
                GeocodeCacheEntry(
                    cache_key=cache_key,
                    query_text=location_text,
                    formatted_address=result.get("formatted_address", location_text),
                    geo=point,
                    provider="google_geocoding",
                    location_confidence=LocationConfidence.APPROXIMATE,
                )
            )
            return point
