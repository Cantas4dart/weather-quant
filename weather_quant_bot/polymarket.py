from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from .models import CityConfig, MarketOutcome
from .utils import retry

log = logging.getLogger(__name__)


class PolymarketClient:
    """Public market scanner using Gamma plus CLOB price endpoints."""

    def __init__(self, gamma_api: str, clob_api: str, timeout: int = 12) -> None:
        self.gamma_api = gamma_api.rstrip("/")
        self.clob_api = clob_api.rstrip("/")
        self.session = requests.Session()
        self.timeout = timeout

    @retry(times=3, delay=1.0)
    def search_markets(self, query: str, limit: int = 100) -> list[dict[str, Any]]:
        response = self.session.get(
            f"{self.gamma_api}/markets",
            params={"q": query, "active": "true", "closed": "false", "limit": limit},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("markets", [])

    @retry(times=3, delay=0.7)
    def get_prices(self, token_ids: list[str], side: str = "BUY") -> dict[str, float]:
        if not token_ids:
            return {}
        response = self.session.get(
            f"{self.clob_api}/prices",
            params={"token_ids": ",".join(token_ids), "sides": ",".join([side] * len(token_ids))},
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw = response.json()
        return {token: float((raw.get(token) or {}).get(side, 0.0)) for token in token_ids}

    def scan_weather_markets(self, city: CityConfig, query_terms: list[str], min_liquidity: float) -> list[MarketOutcome]:
        markets: list[MarketOutcome] = []
        seen: set[str] = set()
        for term in query_terms:
            query = f"{term} {city.name}"
            raw_markets = self.search_markets(query)
            log.info("polymarket scan query=%r city=%s raw_markets=%d", query, city.name, len(raw_markets))
            for raw in raw_markets:
                market_id = str(raw.get("id") or raw.get("conditionId") or "")
                if not market_id or market_id in seen:
                    continue
                question = str(raw.get("question") or raw.get("title") or "")
                if not self._matches_city(question, city):
                    continue
                liquidity = float(raw.get("liquidityNum") or raw.get("liquidity") or 0.0)
                if liquidity < min_liquidity:
                    continue
                seen.add(market_id)
                markets.extend(self._extract_outcomes(raw, city, liquidity))
        log.info("polymarket scan city=%s accepted_outcomes=%d", city.name, len(markets))
        return markets

    def _matches_city(self, question: str, city: CityConfig) -> bool:
        text = question.lower()
        return any(term.lower() in text for term in city.slug_terms)

    def _extract_outcomes(self, raw: dict[str, Any], city: CityConfig, liquidity: float) -> list[MarketOutcome]:
        question = str(raw.get("question") or raw.get("title") or "")
        market_id = str(raw.get("id") or raw.get("conditionId") or "")
        end_time = self._parse_time(raw.get("endDate") or raw.get("end_date_iso") or raw.get("endTime"))
        url = raw.get("url") or f"https://polymarket.com/event/{raw.get('slug', market_id)}"
        outcomes = raw.get("outcomes") or []
        prices = raw.get("outcomePrices") or []
        token_ids = raw.get("clobTokenIds") or raw.get("tokens") or []
        parsed: list[MarketOutcome] = []
        if isinstance(outcomes, str):
            import json

            outcomes = json.loads(outcomes)
        if isinstance(prices, str):
            import json

            prices = json.loads(prices)
        if isinstance(token_ids, str):
            import json

            token_ids = json.loads(token_ids)

        for index, label in enumerate(outcomes):
            price = float(prices[index]) if index < len(prices) and prices[index] not in (None, "") else 0.0
            token = token_ids[index] if index < len(token_ids) else None
            side = "YES" if str(label).lower() not in {"no", "false"} else "NO"
            parsed.append(
                MarketOutcome(
                    market_id=market_id,
                    question=question,
                    city_name=city.name,
                    bucket_label=str(label),
                    side=side,
                    price=price,
                    token_id=str(token) if token else None,
                    liquidity=liquidity,
                    volume=float(raw.get("volumeNum") or raw.get("volume") or 0.0),
                    end_time=end_time,
                    url=url,
                )
            )
        return parsed

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def parse_temperature_bucket(label: str, question: str = "") -> tuple[float | None, float | None]:
    """Return bucket bounds in Celsius with range/direction and F-to-C handling."""
    text = f"{label} {question}".replace("°", " ").replace("Â°", " ")
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
    lower = upper = None
    low_text = text.lower()
    if "below" in low_text or "under" in low_text or "less than" in low_text:
        upper = nums[0] if nums else None
    elif "above" in low_text or "over" in low_text or "or higher" in low_text or "+" in low_text:
        lower = nums[0] if nums else None
    elif len(nums) >= 2:
        lower, upper = min(nums[0], nums[1]), max(nums[0], nums[1])
    elif len(nums) == 1:
        lower, upper = nums[0] - 0.5, nums[0] + 0.5
    if _looks_fahrenheit(low_text, nums):
        lower = _f_to_c(lower) if lower is not None else None
        upper = _f_to_c(upper) if upper is not None else None
    return lower, upper


def _looks_fahrenheit(text: str, nums: list[float]) -> bool:
    if " c" in text or "celsius" in text:
        return False
    if " f" in text or "fahrenheit" in text:
        return True
    return bool(nums and max(nums) > 55)


def _f_to_c(value: float) -> float:
    return (value - 32.0) * 5.0 / 9.0
