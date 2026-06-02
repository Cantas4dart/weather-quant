from __future__ import annotations

from datetime import date, datetime

from .db import BotDB


class BiasManager:
    """Stores forecast-vs-observed errors and returns decayed city bias."""

    def __init__(self, db_path: str, half_life_days: float = 21.0) -> None:
        self.db_path = db_path
        self.half_life_days = half_life_days
        self.db = BotDB(db_path)

    def record_pair(
        self,
        city: str,
        target_date: date,
        source: str,
        forecast_high_c: float,
        observed_high_c: float,
    ) -> None:
        error = observed_high_c - forecast_high_c
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO forecast_errors
                (city, target_date, source, forecast_high_c, observed_high_c, error_c, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    city,
                    target_date.isoformat(),
                    source,
                    forecast_high_c,
                    observed_high_c,
                    error,
                    datetime.utcnow().isoformat(),
                ),
            )

    def get_bias(self, city: str, source: str | None = None, max_days: int = 180) -> float:
        query = """
            SELECT target_date, error_c FROM forecast_errors
            WHERE city = ? AND target_date >= date('now', ?)
        """
        params: list[object] = [city, f"-{max_days} day"]
        if source:
            query += " AND source = ?"
            params.append(source)
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return 0.0
        today = date.today()
        weighted_error = 0.0
        weight_sum = 0.0
        for target_date, error_c in rows:
            age = max((today - date.fromisoformat(target_date)).days, 0)
            weight = 0.5 ** (age / self.half_life_days)
            weighted_error += float(error_c) * weight
            weight_sum += weight
        return weighted_error / weight_sum if weight_sum else 0.0

    def should_alert(self, city: str, market_id: str, strategy: str, cooldown_minutes: int) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT created_at FROM alerts
                WHERE city = ? AND market_id = ? AND strategy = ?
                """,
                (city, market_id, strategy),
            ).fetchone()
        if not row:
            return True
        last = datetime.fromisoformat(row[0])
        return (datetime.utcnow() - last).total_seconds() >= cooldown_minutes * 60

    def mark_alerted(self, city: str, market_id: str, strategy: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO alerts (city, market_id, strategy, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (city, market_id, strategy, datetime.utcnow().isoformat()),
            )
