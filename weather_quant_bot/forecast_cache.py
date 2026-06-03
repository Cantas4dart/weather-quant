"""Forecast caching with hourly rate limiting.

This module implements a caching strategy where forecasts are updated
hourly at 30 minutes past the hour, and cached for the entire hour.
This prevents rate limiting while ensuring markets are properly scanned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


class ForecastCache:
    """Manages forecast caching with hourly rate limiting.
    
    Strategy:
    - Only fetch new forecasts at minute 30 of each hour
    - Cache the forecast for the entire hour
    - Reuse cached forecast for all requests within the hour
    """

    def __init__(self) -> None:
        """Initialize the forecast cache."""
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_timestamps: dict[str, datetime] = {}

    def should_fetch_forecast(self, city_key: str) -> bool:
        """Check if forecast should be fetched for this city.
        
        Returns True only at 30+ minutes past the hour, or if no cache exists.
        
        Args:
            city_key: Unique identifier for the city (e.g., city.name or lat/lon)
            
        Returns:
            True if forecast should be fetched, False otherwise
        """
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        
        # Only fetch between minute 30 and minute 59
        if current_minute < 30:
            if city_key in self._cache:
                log.debug(
                    "forecast cache hit for %s at %02d:%02d (cache from %s)",
                    city_key,
                    now.hour,
                    now.minute,
                    self._cache_timestamps[city_key].strftime("%H:%M"),
                )
                return False
            else:
                # No cache yet, need to fetch
                log.debug("forecast cache miss for %s - no cached forecast yet", city_key)
                return True
        
        # At minute 30+, check if cache is from current hour
        cache_time = self._cache_timestamps.get(city_key)
        if cache_time is None:
            log.debug("forecast cache miss for %s at %02d:%02d - no cache", city_key, now.hour, now.minute)
            return True
        
        # Check if cached forecast is from current hour
        if cache_time.hour == now.hour and cache_time.day == now.day and cache_time.year == now.year:
            log.debug(
                "forecast cache hit for %s at %02d:%02d (cached at %02d:%02d)",
                city_key,
                now.hour,
                now.minute,
                cache_time.hour,
                cache_time.minute,
            )
            return False
        
        # Cache is stale (from previous hour), fetch new one
        log.debug(
            "forecast cache stale for %s at %02d:%02d (cached at %02d:%02d on different hour/day)",
            city_key,
            now.hour,
            now.minute,
            cache_time.hour,
            cache_time.minute,
        )
        return True

    def get_cached_forecast(self, city_key: str) -> dict[str, Any] | None:
        """Get cached forecast for a city if it exists.
        
        Args:
            city_key: Unique identifier for the city
            
        Returns:
            Cached forecast dict or None if not cached
        """
        return self._cache.get(city_key)

    def cache_forecast(self, city_key: str, forecast: dict[str, Any]) -> None:
        """Cache a forecast for a city.
        
        Args:
            city_key: Unique identifier for the city
            forecast: Forecast data to cache
        """
        now = datetime.now(timezone.utc)
        self._cache[city_key] = forecast
        self._cache_timestamps[city_key] = now
        log.debug(
            "forecast cached for %s at %02d:%02d",
            city_key,
            now.hour,
            now.minute,
        )

    def clear_cache(self, city_key: str | None = None) -> None:
        """Clear cache for one or all cities.
        
        Args:
            city_key: City key to clear, or None to clear all
        """
        if city_key is None:
            self._cache.clear()
            self._cache_timestamps.clear()
            log.debug("forecast cache cleared for all cities")
        else:
            self._cache.pop(city_key, None)
            self._cache_timestamps.pop(city_key, None)
            log.debug("forecast cache cleared for %s", city_key)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring.
        
        Returns:
            Dict with cache stats
        """
        now = datetime.now(timezone.utc)
        stats = {
            "cached_cities": len(self._cache),
            "cities": {}
        }
        for city_key, cache_time in self._cache_timestamps.items():
            age_seconds = (now - cache_time).total_seconds()
            stats["cities"][city_key] = {
                "cached_at": cache_time.isoformat(),
                "age_seconds": age_seconds,
                "is_current_hour": cache_time.hour == now.hour
            }
        return stats
