import logging
import requests
from flask_app.config import Config

logger = logging.getLogger(__name__)

class MarketData:
    def __init__(self):
        self.base_url = Config.TRADIER_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {Config.TRADIER_API_TOKEN}",
            "Accept": "application/json"
        }
        logger.debug(f"Tradier API Headers: {self.headers}")
        logger.debug(f"Tradier Base URL: {self.base_url}")

    def get_spy_data(self):
        """Fetch SPY market data (latest quote)."""
        try:
            logger.debug("Fetching SPY data from Tradier API")
            response = requests.get(
                f"{self.base_url}/markets/quotes",
                headers=self.headers,
                params={"symbols": "SPY"}
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Tradier API Response: {data}")
            quote = data["quotes"]["quote"]
            return {
                "candles": [{
                    "close": quote["last"],
                    "volume": quote["volume"],
                    "datetime": quote["trade_date"]
                }]
            }
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error fetching SPY data: {str(http_err)}")
            logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
            return None
        except Exception as e:
            logger.error(f"Error fetching SPY data: {str(e)}")
            return None

    def get_price_history(self, symbol, period_type="day", period="1", frequency_type="minute", frequency=1):
        """Fetch price history for a given symbol using Tradier's history endpoint."""
        try:
            interval_map = {
                "minute": {
                    1: "1min",
                    5: "5min",
                    15: "15min"
                },
                "daily": "daily",
                "weekly": "weekly",
                "monthly": "monthly"
            }
            interval = interval_map.get(frequency_type.lower(), {}).get(frequency, "daily")

            logger.debug(f"Fetching price history for {symbol} with interval {interval}")
            response = requests.get(
                f"{self.base_url}/markets/history",
                headers=self.headers,
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "start": "2025-03-25",
                    "end": "2025-03-30"
                }
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Tradier API Response: {data}")
            history = data["history"]["day"]
            candles = [
                {
                    "close": day["close"],
                    "volume": day["volume"],
                    "datetime": day["date"]
                }
                for day in history
            ]
            return {"candles": candles}
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error fetching price history for {symbol}: {str(http_err)}")
            logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
            return None
        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {str(e)}")
            return None

    def screen_stocks(self, symbols, min_price=0, max_price=float('inf'), min_volume=0, market_cap_filter="Any"):
        """Screen stocks based on given criteria using Tradier quotes."""
        try:
            symbols_str = ",".join(symbols)
            logger.debug(f"Fetching quotes for symbols: {symbols_str}")
            response = requests.get(
                f"{self.base_url}/markets/quotes",
                headers=self.headers,
                params={"symbols": symbols_str}
            )
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Tradier API Response: {data}")
            quotes = data["quotes"]["quote"]
            if isinstance(quotes, dict):
                quotes = [quotes]

            stock_data = {}
            for quote in quotes:
                symbol = quote["symbol"]
                stock_data[symbol] = {
                    "price": quote["last"],
                    "volume": quote["volume"],
                    "market_cap": self._get_approximate_market_cap(symbol)
                }

            filtered_stocks = []
            for symbol, data in stock_data.items():
                price = data["price"]
                volume = data["volume"]
                market_cap = data["market_cap"]

                if (min_price <= price <= max_price and
                    volume >= min_volume and
                    self._match_market_cap_filter(market_cap, market_cap_filter)):
                    filtered_stocks.append((symbol, price, market_cap, volume))

            return filtered_stocks

        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error screening stocks: {str(http_err)}")
            logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
            return []
        except Exception as e:
            logger.error(f"Error screening stocks: {str(e)}")
            return []

    def _get_approximate_market_cap(self, symbol):
        """Return approximate market cap (in millions) for demo purposes."""
        market_caps = {
            "AAPL": 3000000,
            "MSFT": 2500000,
            "GOOGL": 1800000,
            "AMZN": 1700000,
            "TSLA": 800000,
            "NVDA": 600000,
            "JPM": 500000,
            "BAC": 300000,
            "WMT": 400000,
            "KO": 250000
        }
        return market_caps.get(symbol, 0)

    def _match_market_cap_filter(self, market_cap, filter_text):
        """Match market cap against the selected filter."""
        if filter_text == "Any":
            return True
        elif filter_text == "< $2B":
            return market_cap < 2000000
        elif filter_text == "$2B - $10B":
            return 2000000 <= market_cap <= 10000000
        elif filter_text == "> $10B":
            return market_cap > 10000000
        return False