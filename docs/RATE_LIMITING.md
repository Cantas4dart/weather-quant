# Hourly Forecast Rate Limiting Implementation

## Overview

This implementation introduces an intelligent hourly rate limiting system for weather forecasts to prevent API rate limiting while ensuring markets are properly scanned at appropriate intervals.

## How It Works

### Rate Limiting Strategy

- **Fetch Window**: Forecasts are only fetched between **:30 and :59 of each hour** (30+ minutes past the hour)
- **Cache Duration**: Forecasts are cached and reused for the entire hour
- **Cache Miss Handling**: If no cache exists initially, fetches immediately to bootstrap the system
- **Fallback**: If a fetch fails during the update window, uses the previously cached forecast if available

### Timeline Example

```
00:15 - Using cached forecast from 00:30 of previous hour
00:29 - Still using cached forecast (do not fetch yet)
00:30 - Check for update, fetch new forecast if cache is stale
00:31-00:59 - Using newly fetched and cached forecast
01:00-01:29 - Using cached forecast from 00:30
01:30 - Check for update again
```

## Implementation Details

### New Files

#### `weather_quant_bot/forecast_cache.py`
A new caching module that implements the `ForecastCache` class:

- **`should_fetch_forecast(city_key)`**: Determines if a fresh forecast should be fetched based on:
  - Current time (only between :30 and :59)
  - Cached forecast age and validity
  - Whether cache is from the current hour

- **`get_cached_forecast(city_key)`**: Retrieves a cached forecast

- **`cache_forecast(city_key, forecast)`**: Stores a forecast with timestamp

- **`clear_cache(city_key=None)`**: Clears cache for specific city or all cities

- **`get_cache_stats()`**: Returns cache statistics for monitoring

### Modified Files

#### `weather_quant_bot/collector.py`
Updated the `WeatherCollector` class to integrate forecast caching:

1. Added `ForecastCache` import and global cache instance
2. Updated `__init__()` to accept optional cache parameter
3. Modified `collect()` method to:
   - Check `should_fetch_forecast()` before fetching
   - Cache fresh forecasts when fetched
   - Use cached forecasts when available
   - Fall back to cached data if API call fails
4. Added `get_cache_stats()` method for monitoring

**Key Changes in `collect()` method**:
```python
# Check if we should fetch (only at :30+ of each hour)
should_fetch = self.forecast_cache.should_fetch_forecast(city_cache_key)

if should_fetch:
    # Fetch and cache fresh forecast
    om = self.fetch_open_meteo(city)
    self.forecast_cache.cache_forecast(city_cache_key, om)
else:
    # Use cached forecast
    om = self.forecast_cache.get_cached_forecast(city_cache_key)
```

## Benefits

### Rate Limiting Prevention
- **Reduced API Calls**: Typically reduces open-meteo API calls by **94%** (from every 3 minutes to hourly)
- **Predictable Load**: Single fetch per city per hour at a fixed time
- **API Compliance**: Respects rate limits by spacing requests appropriately

### Market Scanning Integrity
- **Hourly Updates**: Markets are scanned with fresh forecasts every hour
- **Consistent Analysis**: All analyses within an hour use the same forecast data
- **Fallback Mechanism**: If fetch fails, previously cached forecast ensures continuity

### System Reliability
- **Graceful Degradation**: Uses cached forecast if API is temporarily unavailable
- **Bootstrap Handling**: Automatically fetches first forecast if cache doesn't exist
- **Monitoring**: `get_cache_stats()` provides visibility into cache performance

## Logging

The implementation adds detailed logging for cache operations:

- `forecast fetched and cached for {city}` - New forecast fetched and cached
- `using cached forecast for {city} (within same hour)` - Cache hit, reusing data
- `using cached forecast for {city} after fetch failure` - Fallback to cache after API error
- `forecast cache hit for {city}` - Cache hit at minute < 30
- `forecast cache stale for {city}` - Cache from previous hour, fetching fresh data

Enable debug logging to see all cache operations:
```python
import logging
logging.getLogger("weather_quant_bot.forecast_cache").setLevel(logging.DEBUG)
```

## Configuration

No configuration changes required. The rate limiting is automatic based on the system clock.

### Optional: Custom Cache Instance

To use a custom cache instance:
```python
from weather_quant_bot.forecast_cache import ForecastCache
from weather_quant_bot.collector import WeatherCollector

custom_cache = ForecastCache()
collector = WeatherCollector(forecast_cache=custom_cache)
```

### Optional: Testing with Different Times

For testing, you can temporarily modify time comparison logic in `forecast_cache.py`:
```python
# For testing, override now() with a mock time
# now = datetime(2024, 6, 3, 14, 35, 0, tzinfo=timezone.utc)  # Test at :35
```

## API Call Reduction

### Before Implementation
- Scan interval: 180 seconds (3 minutes)
- Cities: 4 (Lagos, London, Seoul, Ankara)
- API calls per day: 4 cities × 480 scans/day = **1,920 calls/day**

### After Implementation
- Forecast fetches: 1 per city per hour at :30-:59 window
- METAR/TAF fetches: Still happen every 3 minutes (unchanged)
- Forecast API calls per day: 4 cities × 24 hours = **96 calls/day**
- **Reduction: ~95% for forecast APIs**

## Monitoring

To check cache performance in logs:
```bash
grep "forecast cache" logs/weather_quant.log | tail -20
```

To get cache statistics programmatically:
```python
stats = collector.get_cache_stats()
print(f"Cached cities: {stats['cached_cities']}")
for city, info in stats['cities'].items():
    print(f"  {city}: cached {info['age_seconds']}s ago")
```

## Testing

The rate limiting can be tested by running the application across different times:

1. **At :15 - Should use cache**:
   ```
   DEBUG: forecast cache hit for Lagos at 14:15
   ```

2. **At :35 - Should fetch fresh**:
   ```
   INFO: forecast fetched and cached for Lagos
   ```

3. **At :00 of next hour - Should use cache**:
   ```
   DEBUG: forecast cache hit for Lagos at 15:00
   ```

## Future Enhancements

Possible improvements:
- Persistent cache (save to disk) to survive restarts
- Cache statistics API endpoint for monitoring
- Adaptive window sizing based on API rate limit headers
- Per-city cache expiration policies
- Cache warming before market opens
