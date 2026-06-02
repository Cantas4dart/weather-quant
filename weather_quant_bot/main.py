from __future__ import annotations

import argparse
import logging
import os
import signal

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from .analyzer import WeatherMarketAnalyzer
from .bias_manager import BiasManager
from .collector import WeatherCollector
from .config import load_config
from .gp_calibrator import GPCalibrator
from .polymarket import PolymarketClient
from .profit_signal import ProfitSignalEngine
from .tg_alerts import TelegramAlerter, format_profit_plain, format_signal_plain
from .utils import setup_logging

log = logging.getLogger(__name__)


def build_app() -> tuple[dict, WeatherMarketAnalyzer, TelegramAlerter, BiasManager, PolymarketClient]:
    load_dotenv()
    config_path = os.getenv("CONFIG_PATH", "config/config.yaml")
    config = load_config(config_path)
    runtime = config["runtime"]
    setup_logging(runtime["log_path"], os.getenv("LOG_LEVEL", "INFO"))
    bias = BiasManager(os.getenv("DATABASE_PATH", runtime["database_path"]))
    collector = WeatherCollector()
    gp = GPCalibrator(bias)
    poly_cfg = config["polymarket"]
    polymarket = PolymarketClient(poly_cfg["gamma_api"], poly_cfg["clob_api"])
    analyzer = WeatherMarketAnalyzer(config, collector, gp, bias, polymarket)
    chat_ids = os.getenv("TELEGRAM_CHAT_IDS") or os.getenv("TELEGRAM_CHAT_ID", "")
    public_subscribe = os.getenv("TELEGRAM_PUBLIC_SUBSCRIBE", "true").strip().lower() in {"1", "true", "yes", "on"}
    alerter = TelegramAlerter(os.getenv("TELEGRAM_BOT_TOKEN", ""), chat_ids, public_subscribe=public_subscribe)
    return config, analyzer, alerter, bias, polymarket


def scan_once() -> None:
    config, analyzer, alerter, bias, _ = build_app()
    cooldown = int(config["runtime"]["min_alert_cooldown_minutes"])
    dry_run = bool(config["runtime"].get("dry_run", True))
    manual_trading = bool(config["runtime"].get("manual_trading", True))
    log_alerts = bool(config["runtime"].get("log_alerts", True))
    for city in config["cities"]:
        try:
            signals = analyzer.analyze_city(city)
            for signal in signals:
                if not bias.should_alert(signal.city_name, signal.market.market_id, signal.strategy, cooldown):
                    continue
                if log_alerts or manual_trading or dry_run:
                    log.info("MANUAL TRADE INFO\n%s", format_signal_plain(signal))
                if not dry_run and not manual_trading:
                    alerter.send_signal(signal, db=bias.db)
                bias.mark_alerted(signal.city_name, signal.market.market_id, signal.strategy)
        except Exception as exc:
            log.exception("scan failed for %s: %s", city.name, exc)


def scan_exits_once() -> None:
    config, _, alerter, bias, polymarket = build_app()
    cfg = config["strategy"]["profit_taking"]
    if not cfg.get("enabled", True):
        return
    positions = bias.db.list_positions()
    if not positions:
        log.info("exit scan skipped: manual watchlist is empty")
        return
    prices = polymarket.get_prices([p.token_id for p in positions])
    engine = ProfitSignalEngine(
        levels=list(cfg.get("profit_percent_levels", [200, 400, 900])),
        de_risk_price=float(cfg.get("de_risk_price", 0.70)),
        exit_price=float(cfg.get("exit_price", 0.90)),
        stop_loss_price=float(cfg.get("stop_loss_price", 0.35)),
        max_loss_percent=float(cfg.get("max_loss_percent", 55)),
        hard_stop_price=float(cfg.get("hard_stop_price", 0.18)),
    )
    cooldown = int(config["runtime"]["min_alert_cooldown_minutes"])
    dry_run = bool(config["runtime"].get("dry_run", True))
    manual_trading = bool(config["runtime"].get("manual_trading", True))
    for position in positions:
        current_price = prices.get(position.token_id)
        if current_price is None or current_price <= 0:
            continue
        signal = engine.evaluate(position, current_price)
        if not signal or not bias.db.should_exit_alert(position.token_id, signal.action, cooldown):
            continue
        log.info("MANUAL EXIT INFO\n%s", format_profit_plain(signal))
        if not dry_run and not manual_trading:
            alerter.send_profit(signal, db=bias.db)
        bias.db.mark_exit_alerted(position.token_id, signal.action)


def poll_telegram_once() -> None:
    _, _, alerter, bias, _ = build_app()
    try:
        alerter.poll_subscriptions(bias.db)
    except Exception as exc:
        log.exception("telegram subscription poll failed: %s", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weather Terminal alert bot")
    parser.add_argument("--once", action="store_true", help="run one market scan and exit")
    parser.add_argument("--exits-once", action="store_true", help="run one manual-position exit scan and exit")
    args = parser.parse_args()
    config, _, _, _, _ = build_app()
    if args.once:
        scan_once()
        return
    if args.exits_once:
        scan_exits_once()
        return
    scheduler = BlockingScheduler(timezone=config["runtime"].get("timezone", "UTC"))
    scheduler.add_job(scan_once, "interval", seconds=int(config["runtime"]["scan_interval_seconds"]), max_instances=1)
    scheduler.add_job(
        scan_exits_once,
        "interval",
        seconds=int(config["runtime"]["profit_scan_interval_seconds"]),
        max_instances=1,
    )
    scheduler.add_job(poll_telegram_once, "interval", seconds=20, max_instances=1)
    log.info("weather quant bot started")
    
    def shutdown_handler(signum, frame):
        log.info("received signal %s, shutting down gracefully...", signum)
        scheduler.shutdown()
        log.info("weather quant bot stopped")
    
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    poll_telegram_once()
    scan_once()
    scan_exits_once()
    scheduler.start()


if __name__ == "__main__":
    main()
