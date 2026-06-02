from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

from .bias_manager import BiasManager
from .models import CityConfig, GPForecast, WeatherSnapshot


class GPCalibrator:
    """Gaussian-process temperature calibration with seasonal/time features."""

    def __init__(self, bias_manager: BiasManager | None = None) -> None:
        self.bias_manager = bias_manager
        self.models: dict[str, object] = {}

    def _features(self, city: CityConfig, snapshot: WeatherSnapshot, target_date: date) -> dict[str, float]:
        day = target_date.timetuple().tm_yday
        return {
            "lat": city.latitude,
            "lon": city.longitude,
            "sin_doy": math.sin(2 * math.pi * day / 366),
            "cos_doy": math.cos(2 * math.pi * day / 366),
            "current_temp_c": snapshot.current_temp_c or snapshot.forecast_high_c or 0.0,
            "max_so_far_c": snapshot.max_so_far_c or snapshot.current_temp_c or 0.0,
            "dewpoint_c": snapshot.dewpoint_c or 0.0,
            "wind_speed_kt": snapshot.wind_speed_kt or 0.0,
            "pressure_hpa": snapshot.pressure_hpa or 1013.25,
            "raw_forecast_high_c": snapshot.forecast_high_c or snapshot.current_temp_c or 0.0,
        }

    def train_city(self, city_name: str, frame: pd.DataFrame) -> None:
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import RBF, ConstantKernel, Matern, WhiteKernel
        from sklearn.preprocessing import StandardScaler

        required = [
            "lat",
            "lon",
            "sin_doy",
            "cos_doy",
            "current_temp_c",
            "max_so_far_c",
            "dewpoint_c",
            "wind_speed_kt",
            "pressure_hpa",
            "raw_forecast_high_c",
            "observed_high_c",
        ]
        clean = frame[required].dropna()
        if len(clean) < 25:
            raise ValueError(f"Need at least 25 rows to train GP for {city_name}; got {len(clean)}")
        x = clean[required[:-1]].to_numpy(dtype=float)
        y = clean["observed_high_c"].to_numpy(dtype=float)
        scaler = StandardScaler().fit(x)
        kernel = ConstantKernel(1.0) * (RBF(length_scale=1.5) + Matern(length_scale=1.5, nu=1.5)) + WhiteKernel(
            noise_level=0.35
        )
        model = GaussianProcessRegressor(kernel=kernel, alpha=0.05, normalize_y=True, n_restarts_optimizer=3)
        model.fit(scaler.transform(x), y)
        self.models[city_name] = {"model": model, "scaler": scaler, "columns": required[:-1]}

    def predict(self, city: CityConfig, snapshot: WeatherSnapshot, target_date: date | None = None) -> GPForecast:
        target = target_date or date.today()
        features = self._features(city, snapshot, target)
        bias = self.bias_manager.get_bias(city.name) if self.bias_manager else 0.0
        fallback_mean = features["raw_forecast_high_c"] + bias
        fallback_sigma = self._fallback_sigma(city, snapshot)

        bundle = self.models.get(city.name)
        if not bundle:
            mean = fallback_mean
            sigma = fallback_sigma
        else:
            x = np.array([[features[col] for col in bundle["columns"]]], dtype=float)
            x_scaled = bundle["scaler"].transform(x)
            mean_arr, std_arr = bundle["model"].predict(x_scaled, return_std=True)
            mean = float(mean_arr[0]) + bias
            sigma = max(float(std_arr[0]), 0.45)

        return GPForecast(
            city_name=city.name,
            target_date=target.isoformat(),
            mean_high_c=mean,
            sigma_c=sigma,
            p10_c=float(norm.ppf(0.10, loc=mean, scale=sigma)),
            p90_c=float(norm.ppf(0.90, loc=mean, scale=sigma)),
            bias_c=bias,
            features=features,
        )

    def bucket_probability(self, forecast: GPForecast, lower_c: float | None, upper_c: float | None) -> float:
        lo = -np.inf if lower_c is None else lower_c
        hi = np.inf if upper_c is None else upper_c
        return float(norm.cdf(hi, forecast.mean_high_c, forecast.sigma_c) - norm.cdf(lo, forecast.mean_high_c, forecast.sigma_c))

    def _fallback_sigma(self, city: CityConfig, snapshot: WeatherSnapshot) -> float:
        base = {"low": 0.85, "medium": 1.15, "high": 1.55}.get(city.volatility, 1.2)
        if snapshot.current_temp_c is None:
            base += 0.35
        if snapshot.source != "METAR+OpenMeteo":
            base += 0.25
        return base

