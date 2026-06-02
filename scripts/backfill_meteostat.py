from __future__ import annotations

import argparse
from datetime import datetime

from meteostat import Daily, Point

from weather_quant_bot.bias_manager import BiasManager
from weather_quant_bot.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill 1-5 years of daily observed highs via Meteostat.")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--db", default="data/weather_quant.db")
    parser.add_argument("--years", type=int, default=3)
    args = parser.parse_args()

    cfg = load_config(args.config)
    bias = BiasManager(args.db)
    end = datetime.utcnow()
    start = datetime(end.year - max(1, min(args.years, 5)), end.month, end.day)
    for city in cfg["cities"]:
        data = Daily(Point(city.latitude, city.longitude), start, end).fetch()
        for idx, row in data.iterrows():
            if row.get("tmax") == row.get("tmax"):
                # Store climatology as a neutral forecast baseline until model forecasts are archived.
                bias.record_pair(city.name, idx.date(), "meteostat_climatology", float(row["tmax"]), float(row["tmax"]))
        print(f"backfilled {city.name}: {len(data)} rows")


if __name__ == "__main__":
    main()

