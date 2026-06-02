# Weather Terminal

Production-grade Python information bot for Polymarket daily high-temperature markets. It is tuned for manual trading: alerts are logged by default, Telegram is optional, and no order execution is included. It prioritizes aviation/METAR and TAF observations, calibrated airport settlement data, Gaussian-process uncertainty, city-specific bias, late-day reversal risk, longshot convexity, near-certainty grinding, and profit-taking alerts.

This is alerting software, not financial advice. Keep stakes small, treat every "sure thing" as capable of failing, and verify market resolution rules before trading.

## Structure

```text
weather_quant_bot/
  collector.py          # METAR priority + Open-Meteo fallback + Herbie hook
  db.py                 # lightweight storage facade
  gp_calibrator.py      # RBF + Matern Gaussian Process calibration
  bias_manager.py       # SQLite forecast-vs-observed bias store
  reversal_detector.py  # late-day leader fade detector
  profit_signal.py      # profit-taking, de-risk, and stop-loss alerts
  polymarket.py         # Gamma/CLOB public market scanning
  analyzer.py           # strategy orchestration and edge math
  tg_alerts.py          # Telegram formatting
  main.py               # APScheduler persistent entry point
config/config.yaml      # cities, stations, strategy thresholds
scripts/                # VPS setup and Meteostat backfill
deploy/                 # systemd service
docs/                   # sample alerts and backtesting guide
```

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m weather_quant_bot.main
```

Default mode is manual/log-only. Watch `logs/weather_quant.log` for actionable entries and exits:

```bash
tail -f logs/weather_quant.log
```

Set `runtime.manual_trading: false`, `runtime.dry_run: false`, and `TELEGRAM_BOT_TOKEN` only if you want Telegram push alerts. With `TELEGRAM_PUBLIC_SUBSCRIBE=true`, anyone can open the bot in Telegram and send `/start` to subscribe or `/stop` to unsubscribe. `TELEGRAM_CHAT_IDS` is optional and can seed one chat ID or a comma-separated list for admin/default recipients.

Telegram public access:

```text
/start      subscribe this chat to alerts
/stop       unsubscribe this chat
/help       show commands
```

## Manual Position Watchlist

After you manually enter a trade, add it to the local watchlist so the bot can log profit-taking or stop-loss alerts:

```bash
python scripts/add_position.py --city Lagos --market-id 123 --token-id 456 --side YES --entry-price 0.06 --size-usd 5 --notes "DNMM longshot"
```

The bot polls current CLOB prices and logs:

- TAKE PROFIT at configured +200%, +400%, and +900% gain levels.
- DE-RISK when price reaches 70c while uncertainty remains.
- SELL/EXIT CHOICE when price reaches 90c.
- STOP LOSS when price drops below the configured stop and loss threshold.
- HARD STOP LOSS when price collapses to the hard-stop threshold.

## Data Sources

- METAR from aviationweather.gov is the first live observation source.
- TAF from aviationweather.gov is used as an airport-side timing/confirmation layer, not as the main model.
- Open-Meteo supplies lightweight hourly/daily forecast fallback.
- Meteostat supports historical backfill.
- Herbie is treated as an optional production hook for NOAA/NCEP model guidance.
- Polymarket Gamma and CLOB endpoints scan active markets and prices.

## Strategy Discipline

- Micro longshots: only 2-10c YES buckets with model probability and EV above threshold, targeting 10x+ payout.
- Late-day reversals: final 4-8 hours, fade current leader only when live METAR and GP uncertainty show reversal risk.
- Near-certainty grind: 90-99c YES only when settlement is nearly locked and edge remains positive.
- Profit exits and stop losses: alert at +200%, +400%, +900%, 70c de-risk, 90c exit-choice, 35c stop-loss, and 18c hard-stop defaults.
- Manual logs include evidence, TAF context, failure modes, and confirmation rules so you can decide instead of blindly following a label.
- Entry signals include a suggested TP/SL plan, while the manual watchlist separately alerts when those TP/SL conditions are actually hit.

## Ubuntu VPS Deployment

```bash
sudo adduser --system --group --home /opt/weather-terminal weatherbot
sudo mkdir -p /opt/weather-terminal
sudo chown -R "$USER":"$USER" /opt/weather-terminal
rsync -av ./ /opt/weather-terminal/
cd /opt/weather-terminal
bash scripts/setup_ubuntu.sh
cp .env.example .env
nano .env
sudo cp deploy/weather-terminal.service /etc/systemd/system/weather-terminal.service
sudo systemctl daemon-reload
sudo systemctl enable --now weather-terminal
sudo journalctl -u weather-terminal -f
```

Security tips: run as the unprivileged `weatherbot` user, keep `.env` mode `600`, use a separate low-capital Polymarket wallet, firewall SSH, and avoid storing exchange credentials on shared machines.

## References

- Polymarket docs: https://docs.polymarket.com
- CLOB price endpoint: https://docs.polymarket.com/api-reference/market-data/get-market-prices-query-parameters
- Python CLOB client package: https://pypi.org/project/py-clob-client/
- User-provided issue reference: https://github.com/Polymarket/py-clob-client/issues/335
- User-provided PolyWeather reference: https://github.com/yangyuan-zhen/PolyWeather
- Full reference notes: docs/REFERENCES.md
