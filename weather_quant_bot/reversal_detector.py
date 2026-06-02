from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .gp_calibrator import GPCalibrator
from .models import GPForecast, MarketOutcome, WeatherSnapshot


@dataclass
class ReversalAssessment:
    eligible: bool
    score: float
    fade_probability: float
    reasons: list[str]


class LateDayReversalDetector:
    """Detects final-hours leader fade opportunities in volatile cities."""

    CITY_TUNING = {
        "Lagos": 1.15,
        "London": 1.10,
        "Ankara": 1.10,
        "New York City": 1.10,
        "Miami": 1.05,
        "Chicago": 1.15,
        "Hong Kong": 1.10,
        "Istanbul": 1.10,
    }

    def __init__(self, gp: GPCalibrator, min_score: float = 0.66) -> None:
        self.gp = gp
        self.min_score = min_score

    def assess(
        self,
        snapshot: WeatherSnapshot,
        forecast: GPForecast,
        leader: MarketOutcome,
        hours_to_close: float,
        window_start: float = 8.0,
    ) -> ReversalAssessment:
        reasons: list[str] = []
        if hours_to_close < 0 or hours_to_close > window_start:
            return ReversalAssessment(False, 0.0, 0.0, ["outside late-day reversal window"])
        if leader.price < 0.45:
            return ReversalAssessment(False, 0.0, 0.0, ["leader is not strongly priced"])

        max_so_far = snapshot.max_so_far_c or snapshot.current_temp_c or forecast.mean_high_c
        remaining_delta = forecast.mean_high_c - max_so_far
        uncertainty = forecast.sigma_c
        tuning = self.CITY_TUNING.get(snapshot.city.name, 1.0)
        volatility_bonus = {"high": 0.14, "medium": 0.07, "low": 0.0}.get(snapshot.city.volatility, 0.05)
        live_gap_component = max(min((uncertainty - abs(remaining_delta)) / max(uncertainty, 0.1), 1.0), 0.0)
        time_component = max(min((window_start - hours_to_close) / window_start, 1.0), 0.0)
        metar_component = 0.12 if snapshot.metar_raw else 0.0
        score = min((0.52 * live_gap_component + 0.22 * time_component + volatility_bonus + metar_component) * tuning, 0.99)
        fade_probability = min(max(score * (1.0 - leader.price * 0.35), 0.0), 0.99)

        if abs(remaining_delta) <= uncertainty:
            reasons.append("leader not thermally locked versus GP range")
        if snapshot.metar_raw:
            reasons.append("fresh aviation observation available")
        if snapshot.city.volatility == "high":
            reasons.append("city has high late-session swing profile")
        if forecast.p10_c <= max_so_far <= forecast.p90_c:
            reasons.append("current high sits inside calibrated uncertainty band")

        return ReversalAssessment(score >= self.min_score, score, fade_probability, reasons)

    @staticmethod
    def hours_to_close(market: MarketOutcome) -> float:
        if market.end_time is None:
            return 24.0
        end = market.end_time
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - datetime.now(timezone.utc)).total_seconds() / 3600

