from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from .bias_manager import BiasManager
from .collector import WeatherCollector
from .gp_calibrator import GPCalibrator
from .models import CityConfig, MarketOutcome, StrategySignal
from .polymarket import PolymarketClient, parse_temperature_bucket
from .reversal_detector import LateDayReversalDetector
from .utils import format_temperature, format_temp_range

log = logging.getLogger(__name__)


class WeatherMarketAnalyzer:
    def __init__(
        self,
        config: dict,
        collector: WeatherCollector,
        gp: GPCalibrator,
        bias: BiasManager,
        polymarket: PolymarketClient,
    ) -> None:
        self.config = config
        self.collector = collector
        self.gp = gp
        self.bias = bias
        self.polymarket = polymarket
        reversal_cfg = config["strategy"]["late_day_reversal"]
        self.reversal = LateDayReversalDetector(gp, min_score=float(reversal_cfg["min_reversal_score"]))

    def analyze_city(self, city: CityConfig) -> list[StrategySignal]:
        log.info("scan city=%s station=%s started", city.name, city.station_id or "lat/lon")
        snapshot = self.collector.collect(city)
        current_temp = format_temperature(snapshot.current_temp_c, city.is_us_city) if snapshot.current_temp_c is not None else "n/a"
        max_temp = format_temperature(snapshot.max_so_far_c, city.is_us_city) if snapshot.max_so_far_c is not None else "n/a"
        log.info(
            "scan city=%s obs source=%s current=%s max_so_far=%s taf=%s",
            city.name,
            snapshot.source,
            current_temp,
            max_temp,
            "yes" if snapshot.taf_raw else "no",
        )
        forecast = self.gp.predict(city, snapshot, date.today())
        mean_high = format_temperature(forecast.mean_high_c, city.is_us_city)
        temp_range = format_temp_range(forecast.p10_c, forecast.p90_c, city.is_us_city)
        sigma = f"{forecast.sigma_c * (9 / 5):.2f}°{'F' if city.is_us_city else 'C'}"
        bias = format_temperature(forecast.bias_c, city.is_us_city)
        log.info(
            "scan city=%s gp mean=%s range=%s sigma=%s bias=%s",
            city.name,
            mean_high,
            temp_range,
            sigma,
            bias,
        )
        markets = self.polymarket.scan_weather_markets(
            city,
            self.config["polymarket"]["weather_query_terms"],
            float(self.config["polymarket"]["min_liquidity_usd"]),
        )
        signals: list[StrategySignal] = []
        signals.extend(self._micro_longshots(markets, snapshot, forecast))
        signals.extend(self._near_certainty(markets, snapshot, forecast))
        signals.extend(self._late_reversals(markets, snapshot, forecast))
        log.info("scan city=%s markets=%d signals=%d finished", city.name, len(markets), len(signals))
        return sorted(signals, key=lambda sig: (sig.confidence, sig.expected_value), reverse=True)

    def _micro_longshots(self, markets, snapshot, forecast) -> list[StrategySignal]:
        cfg = self.config["strategy"]["micro_longshot"]
        if not cfg["enabled"]:
            return []
        out: list[StrategySignal] = []
        for market in markets:
            if market.side != "YES" or not (cfg["price_floor"] <= market.price <= cfg["price_ceiling"]):
                continue
            lower, upper = parse_temperature_bucket(market.bucket_label, market.question)
            if lower is None and upper is None:
                continue
            prob = self.gp.bucket_probability(forecast, lower, upper)
            ev = prob / max(market.price, 0.001) - 1.0
            payout_multiple = 1.0 / max(market.price, 0.001)
            if prob >= cfg["min_model_probability"] and ev >= cfg["min_expected_value"] and payout_multiple >= 10:
                out.append(
                    self._signal(
                        "MICRO LONGSHOT",
                        f"MICRO LONGSHOT - Take YES on {market.bucket_label} at {market.price:.0%}",
                        market,
                        prob,
                        ev,
                        min(0.95, prob / max(market.price, 0.001) / 4),
                        snapshot,
                        forecast,
                        [
                            f"{payout_multiple:.1f}x payout profile",
                            "priced in 2-10c convex zone",
                            "GP probability clears calibrated floor",
                            self._taf_reason(snapshot),
                        ],
                    )
                )
        return out

    def _near_certainty(self, markets, snapshot, forecast) -> list[StrategySignal]:
        cfg = self.config["strategy"]["near_certainty"]
        if not cfg["enabled"]:
            return []
        out: list[StrategySignal] = []
        for market in markets:
            if market.side != "YES" or market.price < self.config["polymarket"]["near_certainty_min_price"]:
                continue
            lower, upper = parse_temperature_bucket(market.bucket_label, market.question)
            if lower is None and upper is None:
                continue
            prob = self.gp.bucket_probability(forecast, lower, upper)
            edge = prob - market.price
            if prob >= cfg["min_model_probability"] and edge >= cfg["min_edge"]:
                out.append(
                    self._signal(
                        "NEAR-CERTAINTY GRIND",
                        f"NEAR-CERTAINTY GRIND - Take YES on {market.bucket_label}",
                        market,
                        prob,
                        edge,
                        min(0.99, prob),
                        snapshot,
                        forecast,
                        [
                            "bucket nearly locked by live obs and GP range",
                            "small edge on high-probability capital turn",
                            self._taf_reason(snapshot),
                        ],
                    )
                )
        return out

    def _late_reversals(self, markets, snapshot, forecast) -> list[StrategySignal]:
        cfg = self.config["strategy"]["late_day_reversal"]
        if not cfg["enabled"] or not markets:
            return []
        leader = max(markets, key=lambda m: m.price)
        hours_to_close = self.reversal.hours_to_close(leader)
        assessment = self.reversal.assess(snapshot, forecast, leader, hours_to_close, cfg["window_start_hours_before_close"])
        if not assessment.eligible:
            return []
        no_price = max(1.0 - leader.price, 0.01)
        synthetic = MarketOutcome(**{**leader.__dict__, "side": "NO", "price": no_price})
        ev = assessment.fade_probability / no_price - 1.0
        if ev <= 0:
            return []
        return [
            self._signal(
                "FADE THE LEADER",
                f"FADE THE LEADER - Take NO on {leader.bucket_label}",
                synthetic,
                assessment.fade_probability,
                ev,
                assessment.score,
                snapshot,
                forecast,
                assessment.reasons + [self._taf_reason(snapshot), f"{hours_to_close:.1f} hours to close"],
            )
        ]

    def _signal(self, strategy, rec, market, prob, value, confidence, snapshot, forecast, reasons) -> StrategySignal:
        return StrategySignal(
            strategy=strategy,
            recommendation=rec,
            city_name=market.city_name,
            market=market,
            model_probability=prob,
            implied_probability=market.price,
            edge=prob - market.price,
            expected_value=value,
            confidence=confidence,
            reasons=[reason for reason in reasons if reason],
            failure_modes=self._failure_modes(strategy),
            confirmation_rules=self._confirmation_rules(strategy),
            risk_plan=self._risk_plan(strategy, market),
            snapshot=snapshot,
            forecast=forecast,
            created_at=datetime.now(timezone.utc),
        )

    def _taf_reason(self, snapshot) -> str:
        if snapshot.taf_summary:
            return f"TAF confirmation layer: {snapshot.taf_summary}"
        return "TAF unavailable; airport weather timing is not independently confirmed"

    def _failure_modes(self, strategy: str) -> list[str]:
        common = [
            "market resolution source differs from assumed airport station",
            "late official observation revises the apparent high",
        ]
        if strategy == "MICRO LONGSHOT":
            return common + ["tail bucket never gets close enough for liquidity or profit exit"]
        if strategy == "FADE THE LEADER":
            return common + ["leader bucket locks before expected reversal window develops"]
        return common + ["one high-confidence miss can erase many small near-certainty wins"]

    def _confirmation_rules(self, strategy: str) -> list[str]:
        if strategy == "MICRO LONGSHOT":
            return [
                "fresh METAR trends toward the bucket before price reprices",
                "TAF/cloud/wind timing does not cap the late-day high",
            ]
        if strategy == "FADE THE LEADER":
            return [
                "next METAR fails to extend the current high",
                "GP p90 remains outside the leader bucket after latest observation",
            ]
        return [
            "current official high already sits inside the bucket",
            "next METAR and GP p10 keep the bucket above loss threshold",
        ]

    def _risk_plan(self, strategy: str, market: MarketOutcome) -> list[str]:
        cfg = self.config["strategy"]["profit_taking"]
        entry = max(market.price, 0.001)
        levels = list(cfg.get("profit_percent_levels", [200, 400, 900]))
        take_profit_prices = [min(entry * (1.0 + level / 100.0), 0.99) for level in levels]
        de_risk = float(cfg.get("de_risk_price", 0.70))
        exit_price = float(cfg.get("exit_price", 0.90))
        stop = float(cfg.get("stop_loss_price", 0.35))
        hard_stop = float(cfg.get("hard_stop_price", 0.18))

        if strategy == "MICRO LONGSHOT":
            return [
                f"Suggested entry: only near current price {entry:.1%}; avoid chasing above {min(entry * 1.5, 0.20):.1%}",
                "TP: sell enough to recover stake if price reaches "
                + ", ".join(f"{price:.1%}" for price in take_profit_prices[:3]),
                f"De-risk: sell partial at {de_risk:.0%}; exit-choice at {exit_price:.0%} unless station is near lock",
                f"SL: cut if price falls to {min(stop, max(entry * 0.45, hard_stop)):.1%} or next METAR/TAF breaks the heat thesis",
            ]
        if strategy == "FADE THE LEADER":
            return [
                f"Suggested entry: NO near {entry:.1%}; size smaller because leader fades are timing-sensitive",
                f"TP: de-risk near {min(entry * 2.0, de_risk):.1%}, then scale out toward {de_risk:.0%}-{exit_price:.0%}",
                f"SL: cut if NO falls below {min(stop, max(entry * 0.55, hard_stop)):.1%} or leader bucket locks on next METAR",
                "Invalidation: current high moves decisively into leader bucket with shrinking GP uncertainty",
            ]
        return [
            f"Suggested entry: only if spread allows fill near {entry:.1%}; avoid overpaying for low upside",
            f"TP: exit or reduce quickly at {exit_price:.0%}; near-certainty trades are not meant to become binary hope",
            f"SL: cut on thesis break or price below {max(stop, entry - 0.08):.1%}; one miss can erase many grinds",
            "Invalidation: official station leaves bucket path or GP p10 no longer supports the bucket",
        ]
