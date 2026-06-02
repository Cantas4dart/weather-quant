from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CityConfig:
    name: str
    slug_terms: list[str]
    station_id: str | None
    latitude: float
    longitude: float
    timezone: str
    preferred: bool = True
    volatility: str = "medium"


@dataclass
class WeatherSnapshot:
    city: CityConfig
    observed_at: datetime
    current_temp_c: float | None
    max_so_far_c: float | None
    source: str
    metar_raw: str | None = None
    taf_raw: str | None = None
    taf_summary: str | None = None
    dewpoint_c: float | None = None
    wind_speed_kt: float | None = None
    pressure_hpa: float | None = None
    forecast_high_c: float | None = None
    forecast_low_c: float | None = None
    source_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GPForecast:
    city_name: str
    target_date: str
    mean_high_c: float
    sigma_c: float
    p10_c: float
    p90_c: float
    bias_c: float
    features: dict[str, float]


@dataclass
class MarketOutcome:
    market_id: str
    question: str
    city_name: str
    bucket_label: str
    side: str
    price: float
    token_id: str | None = None
    liquidity: float = 0.0
    volume: float = 0.0
    end_time: datetime | None = None
    url: str | None = None


@dataclass
class StrategySignal:
    strategy: str
    recommendation: str
    city_name: str
    market: MarketOutcome
    model_probability: float
    implied_probability: float
    edge: float
    expected_value: float
    confidence: float
    reasons: list[str]
    snapshot: WeatherSnapshot
    forecast: GPForecast
    created_at: datetime
    failure_modes: list[str] = field(default_factory=list)
    confirmation_rules: list[str] = field(default_factory=list)
    risk_plan: list[str] = field(default_factory=list)


@dataclass
class Position:
    city_name: str
    market_id: str
    token_id: str
    side: str
    entry_price: float
    size_usd: float
    opened_at: datetime
    current_price: float | None = None
    notes: str = ""
