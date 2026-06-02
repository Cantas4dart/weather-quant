# Reference Materials Used

The project was structured from the user-provided requirements plus these materials:

- Polymarket developer documentation: https://docs.polymarket.com
- Polymarket CLOB market price endpoint: https://docs.polymarket.com/api-reference/market-data/get-market-prices-query-parameters
- Polymarket Python CLOB client package reference: https://pypi.org/project/py-clob-client/
- User-provided SDK issue reference: https://github.com/Polymarket/py-clob-client/issues/335
- User-provided Polymarket SDK reference: https://github.com/Polymarket/py-sdk
- User-provided Climeagent repo reference: https://github.com/Cantas4dart/Climeagent.git
- User-provided PolyWeather repo reference: https://github.com/yangyuan-zhen/PolyWeather
- User-provided airport/station mapping in `station.md`.

Implementation notes from the references that are now reflected in this project:

- PolyWeather's emphasis on TAF as an airport-side confirmation layer is implemented in `collector.py` and surfaced in manual signal logs.
- PolyWeather's warning about bad market-bucket matching is reflected in stricter range/direction parsing and Fahrenheit-to-Celsius normalization in `polymarket.py`.
- PolyWeather's intraday analysis structure is reflected in logged `why it works`, `failure modes`, and `confirmation rules`.
- PolyWeather's separation of weather scans from position monitoring is reflected in separate APScheduler jobs for market scans and exit scans.
- The bot currently uses public Gamma/CLOB REST endpoints for market discovery and price polling, keeping SDK credentials optional because the requested workflow is manual trading and information logging.
