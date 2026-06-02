# Backtesting Guide

Focus every test on realized airport highs, not generic city temperatures.

1. Backfill observations:

```bash
python scripts/backfill_meteostat.py --years 5 --db data/weather_quant.db
```

2. Archive live forecasts and market snapshots every scan. The production bot stores bias pairs; extend this with raw market books before risking capital.

3. Evaluate four ledgers separately:

- Micro longshots: price 2-10c, model probability above configured floor, realized bucket hit rate, max drawdown, payout multiple.
- Late-day reversals: final 4-8 hours only, leader price, METAR high at signal time, final settlement bucket, fade ROI.
- Near-certainty: 90-99c entries, realized loss frequency, whether one loss erases 50+ grinds.
- Profit exits: mark-to-market at +200%, +400%, +900%, 70c, and 90c. Compare hold-to-expiry versus staged exits.

4. Validate across Lagos, London, Seoul, Ankara, NYC, Paris, Tokyo, Miami, Chicago, Beijing, Shanghai, Hong Kong, Istanbul, Madrid, and Toronto before expanding.

5. Promote a city only when edge survives out-of-sample dates, station-specific bias, and realistic CLOB spreads.