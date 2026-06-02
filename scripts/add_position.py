from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from weather_quant_bot.config import load_config
from weather_quant_bot.db import BotDB


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Add a manually opened Polymarket position to the exit watchlist.")
    parser.add_argument("--city", required=True)
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--token-id", required=True)
    parser.add_argument("--side", default="YES", choices=["YES", "NO"])
    parser.add_argument("--entry-price", required=True, type=float, help="Decimal price, e.g. 0.06 for 6c")
    parser.add_argument("--size-usd", type=float, default=0.0)
    parser.add_argument("--notes", default="")
    parser.add_argument("--config", default=os.getenv("CONFIG_PATH", "config/config.yaml"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    db = BotDB(os.getenv("DATABASE_PATH", cfg["runtime"]["database_path"]))
    db.add_position(args.city, args.market_id, args.token_id, args.side, args.entry_price, args.size_usd, args.notes)
    print(f"watching {args.city} {args.side} {args.token_id} from {args.entry_price:.1%}")


if __name__ == "__main__":
    main()
