import time
import logging
import requests
import threading
import yfinance as yf
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from flask_app.config import Config
from flask_app.data.market_calendar import MarketCalendar
from flask_app.data.sentiment import StockSentiment

logger = logging.getLogger(__name__)

class MarketData:
    def __init__(self):
        self.use_alpaca = False  # Set to False to use Tradier for market data
        self.tradier_base_url = Config.TRADIER_BASE_URL
        self.tradier_headers = {
            "Authorization": f"Bearer {Config.TRADIER_API_TOKEN}",
            "Accept": "application/json"
        }
        # Alpaca API for news data
        self.alpaca_base_url = Config.ALPACA_BASE_URL
        self.alpaca_headers = {
            "APCA-API-KEY-ID": Config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": Config.ALPACA_SECRET_KEY
        }
        # Initialize StockSentiment for news sentiment analysis
        self.stock_sentiment = StockSentiment(
            alpaca_base_url=self.alpaca_base_url,
            alpaca_headers=self.alpaca_headers,
            rate_limit_per_second=3.33  # Alpaca's rate limit for news
        )
        self.buy_sell_cache = {}
        self.cache_ttl = 60
        
        # Rate limiting: 200 requests per minute for Alpaca free tier (3.33 requests per second)
        # Tradier: 120 requests per minute (2 requests per second)
        self.rate_limit_per_second = 2  # Use Tradier's rate limit for market data
        self.last_request_time = 0
        self.lock = threading.Lock()
        self.market_calendar = MarketCalendar(timezone=Config.TIMEZONE)
        
    def _rate_limit(self):
        """Enforce rate limiting to avoid exceeding API limits."""
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < (1 / self.rate_limit_per_second):
                time.sleep((1 / self.rate_limit_per_second) - time_since_last)
            self.last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(requests.exceptions.HTTPError),
        before_sleep=lambda retry_state: logger.debug(f"Retrying API request (attempt {retry_state.attempt_number})...")
    )
    def _make_api_request(self, url, params, use_alpaca=False):
        """Make an API request with rate limiting and retry logic."""
        self._rate_limit()
        # Use Alpaca for news, Tradier for market data
        headers = self.alpaca_headers if use_alpaca else self.tradier_headers
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response
        
    def _validate_symbol(self, symbol):
        """Validate that a symbol is a valid U.S. stock ticker."""
        if not isinstance(symbol, str):
            return False
        # U.S. stock tickers are typically 1-5 uppercase letters, optionally with a suffix (e.g., "BRK.A")
        import re
        pattern = r"^[A-Z]{1,5}(\.[A-Z])?$"
        return bool(re.match(pattern, symbol))
    
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

    def screen_stocks(self, symbols):
        """
        Fetch stock data for the given symbols using Tradier quotes.
        Args:
            symbols: List of stock symbols to fetch.
        Returns:
            List of tuples: (symbol, price, market_cap, volume, change_percentage, bid, ask)
        """
        try:
            if not symbols:
                return []

            # Validate symbols
            valid_symbols = [symbol for symbol in symbols if self._validate_symbol(symbol)]
            if not valid_symbols:
                logger.error("No valid symbols provided for screening.")
                return []
            if len(valid_symbols) < len(symbols):
                invalid_symbols = set(symbols) - set(valid_symbols)
                logger.warning(f"Skipping invalid symbols: {invalid_symbols}")

            # Batch request for all symbols using Tradier API
            symbols_str = ",".join(valid_symbols)
            logger.debug(f"Fetching quotes for symbols: {symbols_str}")
            response = self._make_api_request(
                f"{self.tradier_base_url}/markets/quotes",
                params={"symbols": symbols_str},
                use_alpaca=False  # Use Tradier for market data
            )
            raw_response = response.text
            logger.debug(f"Raw Tradier API Response: {raw_response}")
            data = response.json()
            if not isinstance(data, dict) or "quotes" not in data:
                logger.error(f"Invalid Tradier API response: {data}")
                return []

            quotes_data = data["quotes"]
            if not isinstance(quotes_data, dict):
                logger.error(f"Tradier API returned invalid quotes data: {quotes_data}")
                return []

            if "quote" not in quotes_data:
                logger.error(f"No quote data available in Tradier API response: {quotes_data}")
                return []

            quotes = quotes_data["quote"]
            if quotes is None:
                logger.error(f"Tradier API returned null quotes for symbols: {symbols_str}")
                return []

            # Ensure quotes is a list
            if isinstance(quotes, dict):
                quotes = [quotes]
            elif isinstance(quotes, str):
                logger.error(f"Tradier API returned a string instead of a quote object: {quotes}")
                return []
            elif not isinstance(quotes, list):
                logger.error(f"Tradier API returned unexpected quote type: {type(quotes)}, value: {quotes}")
                return []

            quotes_list = quotes
            logger.debug(f"Parsed quotes_list: {quotes_list}")

            stock_data = []
            for quote in quotes_list:
                if not isinstance(quote, dict):
                    logger.warning(f"Skipping invalid quote entry (not a dict): {quote}")
                    continue
                raw_symbol = quote.get("symbol")
                if not raw_symbol:
                    logger.warning(f"Quote missing symbol: {quote}")
                    continue
                symbol = raw_symbol.split('.')[0].upper()
                logger.debug(f"Raw symbol: {raw_symbol}, Normalized symbol: {symbol}")
                market_cap = self._get_approximate_market_cap(symbol)
                logger.debug(f"Market cap for {symbol}: {market_cap}")
                stock_data.append((
                    symbol,
                    quote.get("last", 0),
                    market_cap,
                    quote.get("volume", 0),
                    quote.get("change_percentage", 0.0),
                    quote.get("bid", 0),
                    quote.get("ask", 0)
                ))

            logger.debug(f"Returning stock_data: {stock_data}")
            return stock_data

        except Exception as e:
            logger.error(f"Error in screen_stocks: {str(e)}")
            return []
        
    def get_buy_sell_volume(self, symbols, bid_ask_data=None, force_refresh=False):
        if not symbols:
            return {}

        # Validate symbols
        valid_symbols = [symbol for symbol in symbols if self._validate_symbol(symbol)]
        if not valid_symbols:
            logger.error("No valid symbols provided for buy/sell volume.")
            return {}
        if len(valid_symbols) < len(symbols):
            invalid_symbols = set(symbols) - set(valid_symbols)
            logger.warning(f"Skipping invalid symbols for buy/sell volume: {invalid_symbols}")

        # Initialize results
        results = {}
        current_time = time.time()
        valid_symbols_to_fetch = []

        # Check cache for existing data (unless force_refresh is True)
        if not force_refresh:
            for symbol in valid_symbols:
                if symbol in self.buy_sell_cache:
                    cached_data = self.buy_sell_cache[symbol]
                    if current_time - cached_data["timestamp"] < self.cache_ttl:
                        results[symbol] = (cached_data["buy_volume"], cached_data["sell_volume"])
                        logger.debug(f"Using cached buy/sell volume for {symbol}: {results[symbol]} (age: {int(current_time - cached_data['timestamp'])} seconds)")
                        continue
                valid_symbols_to_fetch.append(symbol)
        else:
            logger.debug("Force refresh enabled; bypassing cache for all symbols")
            valid_symbols_to_fetch = valid_symbols

        if not valid_symbols_to_fetch:
            return results

        # Use provided bid/ask data if available; otherwise, fetch it in a single batch
        if bid_ask_data is None:
            bid_ask_data = {}
            valid_symbols_str = ",".join(valid_symbols_to_fetch)
            logger.debug(f"Fetching bid/ask for symbols in a single batch: {valid_symbols_str}")
            try:
                quote_response = self._make_api_request(
                    f"{self.tradier_base_url}/markets/quotes",
                    params={"symbols": valid_symbols_str},
                    use_alpaca=False  # Use Tradier for market data
                )
                quote_data = quote_response.json().get("quotes", {}).get("quote", {})
                if isinstance(quote_data, dict):
                    quote_data = [quote_data]
                for quote in quote_data:
                    symbol = quote["symbol"].split('.')[0].upper()
                    bid_ask_data[symbol] = (quote.get("bid", 0), quote.get("ask", 0))
            except Exception as e:
                logger.error(f"Error fetching bid/ask data for {valid_symbols_str}: {str(e)}")
                for symbol in valid_symbols_to_fetch:
                    bid_ask_data[symbol] = (0, 0)

        # Fetch total volume as a fallback for all symbols
        total_volumes = {}
        stock_data = self.screen_stocks(symbols=valid_symbols_to_fetch)
        for stock in stock_data:
            symbol = stock[0]
            total_volume = stock[3]
            total_volumes[symbol] = total_volume

        # Define the time range: last 4 hours, aligned with market hours
        current_time_dt = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        current_time_eastern = current_time_dt.astimezone(self.market_calendar.timezone)
        current_date = current_time_eastern.date()

        market_open_utc, market_close_utc = self.market_calendar.get_market_hours(
            current_date,
            market_open_hour=Config.MARKET_OPEN_HOUR,
            market_open_minute=Config.MARKET_OPEN_MINUTE,
            market_close_hour=Config.MARKET_CLOSE_HOUR,
            market_close_minute=Config.MARKET_CLOSE_MINUTE
        )

        if current_time_dt < market_open_utc:
            previous_trading_day = self.market_calendar.get_previous_trading_day(current_date)
            market_open_utc, market_close_utc = self.market_calendar.get_market_hours(
                previous_trading_day,
                market_open_hour=Config.MARKET_OPEN_HOUR,
                market_open_minute=Config.MARKET_OPEN_MINUTE,
                market_close_hour=Config.MARKET_CLOSE_HOUR,
                market_close_minute=Config.MARKET_CLOSE_MINUTE
            )
            end_time = market_close_utc
            start_time = end_time - timedelta(hours=4)
        elif current_time_dt > market_close_utc:
            if not self.market_calendar.is_trading_day(current_date):
                previous_trading_day = self.market_calendar.get_previous_trading_day(current_date)
                market_open_utc, market_close_utc = self.market_calendar.get_market_hours(
                    previous_trading_day,
                    market_open_hour=Config.MARKET_OPEN_HOUR,
                    market_open_minute=Config.MARKET_OPEN_MINUTE,
                    market_close_hour=Config.MARKET_CLOSE_HOUR,
                    market_close_minute=Config.MARKET_CLOSE_MINUTE
                )
            end_time = market_close_utc
            start_time = end_time - timedelta(hours=4)
        else:
            if not self.market_calendar.is_trading_day(current_date):
                previous_trading_day = self.market_calendar.get_previous_trading_day(current_date)
                market_open_utc, market_close_utc = self.market_calendar.get_market_hours(
                    previous_trading_day,
                    market_open_hour=Config.MARKET_OPEN_HOUR,
                    market_open_minute=Config.MARKET_OPEN_MINUTE,
                    market_close_hour=Config.MARKET_CLOSE_HOUR,
                    market_close_minute=Config.MARKET_CLOSE_MINUTE
                )
                end_time = market_close_utc
                start_time = end_time - timedelta(hours=4)
            else:
                end_time = current_time_dt
                start_time = end_time - timedelta(hours=4)
                if start_time < market_open_utc:
                    start_time = market_open_utc

        if end_time > current_time_dt:
            logger.warning(f"End time {end_time} is in the future; adjusting to current time {current_time_dt}")
            end_time = current_time_dt
            start_time = end_time - timedelta(hours=4)
            if start_time < market_open_utc:
                start_time = market_open_utc

        if start_time >= end_time:
            logger.warning(f"Invalid time range: start_time {start_time} is not before end_time {end_time}. Adjusting to previous trading day.")
            previous_trading_day = self.market_calendar.get_previous_trading_day(end_time.date())
            market_open_utc, market_close_utc = self.market_calendar.get_market_hours(
                previous_trading_day,
                market_open_hour=Config.MARKET_OPEN_HOUR,
                market_open_minute=Config.MARKET_OPEN_MINUTE,
                market_close_hour=Config.MARKET_CLOSE_HOUR,
                market_close_minute=Config.MARKET_CLOSE_MINUTE
            )
            end_time = market_close_utc
            start_time = end_time - timedelta(hours=4)

        # Format timestamps for Tradier (YYYY-MM-DD HH:MM:SS)
        start_ts = start_time.strftime("%Y-%m-%d %H:%M:%S")
        end_ts = end_time.strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"Time range for buy/sell volume: start={start_ts}, end={end_ts}")

        # Fetch trade data using Tradier
        trades_by_symbol = defaultdict(list)
        for symbol in valid_symbols_to_fetch:
            logger.debug(f"Fetching timesales for {symbol} from Tradier API")
            try:
                timesales_response = self._make_api_request(
                    f"{self.tradier_base_url}/markets/timesales",
                    params={
                        "symbol": symbol,
                        "interval": "tick",
                        "start": start_ts,
                        "end": end_ts
                    },
                    use_alpaca=False  # Use Tradier for market data
                )
                raw_response = timesales_response.text
                logger.debug(f"Raw timesales response for {symbol}: {raw_response}")
                timesales_data = timesales_response.json()
                if timesales_data is None:
                    logger.error(f"Failed to parse JSON response for {symbol}; response is None")
                    raise ValueError("Timesales response is not valid JSON")
                series = timesales_data.get("series")
                if series is None:
                    logger.warning(f"No trade data available for {symbol} in the specified time range (series is null). Falling back to even split.")
                    total_volume = total_volumes.get(symbol, 0)
                    buy_volume = total_volume // 2 if total_volume is not None else 0
                    sell_volume = total_volume - buy_volume if total_volume is not None else 0
                    results[symbol] = (buy_volume, sell_volume)
                    self.buy_sell_cache[symbol] = {
                        "buy_volume": buy_volume,
                        "sell_volume": sell_volume,
                        "timestamp": current_time
                    }
                    continue
                trades = series.get("data", [])
                trades_by_symbol[symbol] = trades
            except requests.exceptions.HTTPError as http_err:
                error_message = str(http_err)
                if "502" in error_message:
                    logger.warning(f"Tradier API returned a 502 Bad Gateway error for {symbol}. Falling back to even split.")
                elif "401" in error_message or "403" in error_message:
                    logger.warning(f"Cannot fetch buy/sell volume for {symbol}: Unauthorized. Check your Tradier API key or subscription.")
                elif "400" in error_message:
                    logger.error(f"Bad Request error fetching buy/sell volume for {symbol} from Tradier: {error_message}")
                    logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
                elif "429" in error_message:
                    logger.error(f"Rate limit exceeded for Tradier API for {symbol}. Falling back to even split.")
                else:
                    logger.error(f"HTTP Error fetching buy/sell volume for {symbol} from Tradier: {error_message}")
                    logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
                total_volume = total_volumes.get(symbol, 0)
                buy_volume = total_volume // 2 if total_volume is not None else 0
                sell_volume = total_volume - buy_volume if total_volume is not None else 0
                results[symbol] = (buy_volume, sell_volume)
                self.buy_sell_cache[symbol] = {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "timestamp": current_time
                }
            except Exception as e:
                logger.error(f"Error fetching buy/sell volume for {symbol} from Tradier: {str(e)}")
                total_volume = total_volumes.get(symbol, 0)
                buy_volume = total_volume // 2 if total_volume is not None else 0
                sell_volume = total_volume - buy_volume if total_volume is not None else 0
                results[symbol] = (buy_volume, sell_volume)
                self.buy_sell_cache[symbol] = {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "timestamp": current_time
                }

        # Process trades for symbols that were successfully fetched
        for symbol, trades in trades_by_symbol.items():
            bid, ask = bid_ask_data.get(symbol, (0, 0))
            if bid == 0 or ask == 0:
                logger.warning(f"No valid bid/ask data for {symbol}. Falling back to even split.")
                total_volume = total_volumes.get(symbol, 0)
                buy_volume = total_volume // 2 if total_volume is not None else 0
                sell_volume = total_volume - buy_volume if total_volume is not None else 0
                results[symbol] = (buy_volume, sell_volume)
                self.buy_sell_cache[symbol] = {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "timestamp": current_time
                }
                continue

            if not trades:
                logger.warning(f"No trade data available for {symbol} in the specified time range. Falling back to even split.")
                total_volume = total_volumes.get(symbol, 0)
                buy_volume = total_volume // 2 if total_volume is not None else 0
                sell_volume = total_volume - buy_volume if total_volume is not None else 0
                results[symbol] = (buy_volume, sell_volume)
                self.buy_sell_cache[symbol] = {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "timestamp": current_time
                }
                continue

            # Get sentiment score using StockSentiment
            sentiment_score = self.stock_sentiment.get_stock_sentiment(symbol)

            buy_volume = 0
            sell_volume = 0
            recent_buys = 0
            recent_sells = 0
            momentum_window = 5

            for i, trade in enumerate(trades):
                trade_price = trade.get("price", 0)
                trade_volume = trade.get("volume", trade.get("s", 0))

                if trade_price >= ask:
                    buy_volume += trade_volume
                    recent_buys += 1
                elif trade_price <= bid:
                    sell_volume += trade_volume
                    recent_sells += 1
                else:
                    if i >= momentum_window:
                        recent_buys = sum(1 for j in range(i - momentum_window, i) if trades[j]["price"] >= ask)
                        recent_sells = sum(1 for j in range(i - momentum_window, i) if trades[j]["price"] <= bid)
                    total_recent = recent_buys + recent_sells
                    if total_recent > 0:
                        momentum_buy_ratio = recent_buys / total_recent
                    else:
                        momentum_buy_ratio = 0.5

                    sentiment_adjustment = (sentiment_score + 1) / 2
                    buy_ratio = (momentum_buy_ratio + sentiment_adjustment) / 2
                    buy_ratio = max(0, min(1, buy_ratio))
                    sell_ratio = 1 - buy_ratio

                    buy_volume += int(trade_volume * buy_ratio)
                    sell_volume += int(trade_volume * sell_ratio)

                if i >= momentum_window:
                    oldest_trade = trades[i - momentum_window]
                    if oldest_trade["price"] >= ask:
                        recent_buys -= 1
                    elif oldest_trade["price"] <= bid:
                        recent_sells -= 1

            results[symbol] = (buy_volume, sell_volume)
            self.buy_sell_cache[symbol] = {
                "buy_volume": buy_volume,
                "sell_volume": sell_volume,
                "timestamp": current_time
            }
            logger.debug(f"Inferred fresh buy/sell volume for {symbol}: Buy={buy_volume}, Sell={sell_volume}")

        return results

    def _get_approximate_market_cap(self, symbol):
        """Fetch market cap (in millions) using yfinance."""
        try:
            logger.debug(f"Fetching market cap for {symbol} using yfinance")
            ticker = yf.Ticker(symbol)
            info = ticker.info
            market_cap = info.get("marketCap", 0)
            market_cap_millions = market_cap / 1e6
            logger.debug(f"Market cap for {symbol}: {market_cap_millions} million USD")
            return market_cap_millions
        except Exception as e:
            logger.error(f"Error fetching market cap for {symbol} using yfinance: {str(e)}")
            return 0