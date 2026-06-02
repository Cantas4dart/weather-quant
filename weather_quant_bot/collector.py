from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from .models import CityConfig, WeatherSnapshot
from .utils import retry, fahrenheit_to_celsius

log = logging.getLogger(__name__)


class WeatherCollector:
    """Collects fast aviation observations first, then forecast fallbacks."""

    def __init__(self, timeout: int = 12) -> None:
        self.session = requests.Session()
        self.timeout = timeout

    @retry(times=3, delay=0.7)
    def fetch_metar_raw(self, station_id: str) -> str | None:
        url = "https://aviationweather.gov/api/data/metar"
        response = self.session.get(
            url,
            params={"ids": station_id, "format": "raw", "taf": "false"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        text = response.text.strip()
        return text.splitlines()[-1].strip() if text else None

    @retry(times=3, delay=0.7)
    def fetch_taf_raw(self, station_id: str) -> str | None:
        url = "https://aviationweather.gov/api/data/taf"
        response = self.session.get(
            url,
            params={"ids": station_id, "format": "raw"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        text = response.text.strip()
        return " ".join(line.strip() for line in text.splitlines() if line.strip()) if text else None

    def parse_metar(self, raw: str) -> dict[str, float | str | None]:
        try:
            from metar import Metar

            obs = Metar.Metar(raw)
            return {
                "temp_c": obs.temp.value("C") if obs.temp else None,
                "dewpoint_c": obs.dewpt.value("C") if obs.dewpt else None,
                "wind_speed_kt": obs.wind_speed.value("KT") if obs.wind_speed else None,
                "pressure_hpa": obs.press.value("HPA") if obs.press else None,
            }
        except Exception as exc:
            log.warning("METAR parse failed: %s", exc)
            return {"temp_c": None, "dewpoint_c": None, "wind_speed_kt": None, "pressure_hpa": None}

    def summarize_taf(self, raw: str | None) -> str | None:
        if not raw:
            return None
        tokens = raw.split()
        timing = [token for token in tokens if token.startswith(("FM", "TEMPO", "BECMG", "PROB30", "PROB40"))]
        weather = [
            token
            for token in tokens
            if any(code in token for code in ("TS", "SH", "RA", "FG", "BR", "CB", "BKN", "OVC"))
        ]
        parts = []
        if timing:
            parts.append("timing " + ", ".join(timing[:6]))
        if weather:
            parts.append("wx " + ", ".join(weather[:8]))
        return "; ".join(parts) if parts else "no major TAF timing/weather flags parsed"

    @retry(times=3, delay=1.0)
    def fetch_open_meteo(self, city: CityConfig) -> dict[str, Any]:
        url = "https://api.open-meteo.com/v1/forecast"
        temperature_unit = "fahrenheit" if city.is_us_city else "celsius"
        params = {
            "latitude": city.latitude,
            "longitude": city.longitude,
            "hourly": "temperature_2m,wind_speed_10m,pressure_msl",
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": city.timezone,
            "forecast_days": 2,
            "temperature_unit": temperature_unit,
        }
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def collect(self, city: CityConfig) -> WeatherSnapshot:
        metar_raw = None
        taf_raw = None
        taf_summary = None
        parsed = {"temp_c": None, "dewpoint_c": None, "wind_speed_kt": None, "pressure_hpa": None}
        if city.station_id:
            try:
                metar_raw = self.fetch_metar_raw(city.station_id)
                if metar_raw:
                    parsed = self.parse_metar(metar_raw)
            except Exception as exc:
                log.warning("METAR fetch failed for %s/%s: %s", city.name, city.station_id, exc)
            try:
                taf_raw = self.fetch_taf_raw(city.station_id)
                taf_summary = self.summarize_taf(taf_raw)
            except Exception as exc:
                log.warning("TAF fetch failed for %s/%s: %s", city.name, city.station_id, exc)

        details: dict[str, Any] = {}
        forecast_high = None
        forecast_low = None
        max_so_far = parsed["temp_c"]
        try:
            om = self.fetch_open_meteo(city)
            details["open_meteo"] = om
            daily = om.get("daily", {})
            forecast_high = (daily.get("temperature_2m_max") or [None])[0]
            forecast_low = (daily.get("temperature_2m_min") or [None])[0]
            # Convert F back to C for internal storage if US city
            if city.is_us_city:
                if forecast_high is not None:
                    forecast_high = fahrenheit_to_celsius(forecast_high)
                if forecast_low is not None:
                    forecast_low = fahrenheit_to_celsius(forecast_low)
            hourly = om.get("hourly", {})
            temps = [t for t in hourly.get("temperature_2m", [])[:24] if t is not None]
            # Convert F to C for internal storage if US city
            if city.is_us_city:
                temps = [fahrenheit_to_celsius(t) for t in temps]
            if temps:
                candidates = ([max_so_far] if max_so_far is not None else []) + temps
                max_so_far = max(candidates)
        except Exception as exc:
            log.warning("Open-Meteo fallback failed for %s: %s", city.name, exc)

        return WeatherSnapshot(
            city=city,
            observed_at=datetime.now(timezone.utc),
            current_temp_c=parsed["temp_c"],
            max_so_far_c=max_so_far,
            source="METAR+TAF+OpenMeteo" if metar_raw and taf_raw else "METAR+OpenMeteo" if metar_raw else "OpenMeteo",
            metar_raw=metar_raw,
            taf_raw=taf_raw,
            taf_summary=taf_summary,
            dewpoint_c=parsed["dewpoint_c"],
            wind_speed_kt=parsed["wind_speed_kt"],
            pressure_hpa=parsed["pressure_hpa"],
            forecast_high_c=forecast_high,
            forecast_low_c=forecast_low,
            source_details=details,
        )

    def collect_model_guidance(self, city: CityConfig) -> dict[str, float]:
        """Lightweight hook for Herbie/NOAA model guidance; returns empty if unavailable."""
        guidance: dict[str, float] = {}
        try:
            # Herbie downloads GRIB subsets in production. Keep this optional because
            # low-end VPS deployments often run without full GRIB tooling initially.
            import herbie  # noqa: F401

            guidance["herbie_available"] = 1.0
        except Exception:
            guidance["herbie_available"] = 0.0
        return guidance
