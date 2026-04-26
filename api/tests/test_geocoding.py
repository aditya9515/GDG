import pytest

from app.core.config import Settings
from app.repositories.memory import MemoryRepository
from app.services.geocoding import GeocodingService


@pytest.mark.asyncio
async def test_known_location_is_cached_after_lookup():
    repository = MemoryRepository()
    service = GeocodingService(settings=Settings(), repository=repository)

    point = await service.geocode("Shantinagar bridge")

    assert point is not None
    cached = repository.get_geocode_cache("shantinagar bridge")
    assert cached is not None
    assert cached.geo.lat == point.lat
    assert cached.provider == "seeded_known_location"
