import time
import logging
import aiohttp
import tenacity
import yfinance as yf
import asyncio
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
        self.tradier_base_url = Config.TRADIER_BASE_URL
        self.tradier_headers = {
            "Authorization": f"Bearer {Config.TRADIER_API_TOKEN}",
            "Accept": "application/json"
        }
        self.alpaca_base_url = Config.ALPACA_BASE_URL
        self.alpaca_headers = {
            "APCA-API-KEY-ID": Config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": Config.ALPACA_SECRET_KEY,
            "Accept": "application/json"
        }
        self.rate_limit_per_second = 2  # Tradier rate limit: 2 requests/sec
        self.alpaca_rate_limit_per_second = 3.33  # Alpaca rate limit: 200 requests/minute
        self.last_request_time = 0
        self.last_alpaca_request_time = 0
        self.lock = asyncio.Lock()
        self.cache_ttl = 10
        self.stock_cache = {}
        self.buy_sell_cache = {}
        self.stock_sentiment = StockSentiment(
            alpaca_base_url=self.alpaca_base_url,
            alpaca_headers=self.alpaca_headers,
            rate_limit_per_second=self.alpaca_rate_limit_per_second
        )
        self.market_calendar = MarketCalendar()

    async def _rate_limit(self, use_alpaca=True):
        async with self.lock:
            current_time = time.time()
            if use_alpaca:
                time_since_last = current_time - self.last_alpaca_request_time
                rate_limit = self.alpaca_rate_limit_per_second
                last_request_time_ref = 'last_alpaca_request_time'
            else:
                time_since_last = current_time - self.last_request_time
                rate_limit = self.rate_limit_per_second
                last_request_time_ref = 'last_request_time'

            sleep_time = (1 / rate_limit) - time_since_last
            if sleep_time > 0:
                logger.debug(f"Rate limiting {'Alpaca' if use_alpaca else 'Tradier'}: sleeping for {sleep_time:.2f} seconds")
                await asyncio.sleep(sleep_time)
            setattr(self, last_request_time_ref, current_time)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(aiohttp.ClientResponseError),
        before_sleep=lambda retry_state: logger.debug(f"Retrying API request (attempt {retry_state.attempt_number})...")
    )
    async def _make_api_request(self, url, params, use_alpaca=True):
        await self._rate_limit(use_alpaca)
        headers = self.alpaca_headers if use_alpaca else self.tradier_headers
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params) as response:
                try:
                    response.raise_for_status()
                    return await response.json()
                except aiohttp.ClientResponseError as e:
                    error_response = "No response body"
                    try:
                        error_response = await response.text()
                    except Exception as log_err:
                        logger.error(f"Failed to fetch error response body: {str(log_err)}")
                    logger.error(f"ClientResponseError in API request to {url}: Status={e.status}, Message={e.message}, Response={error_response}")
                    raise

    def _validate_symbol(self, symbol):
        if not isinstance(symbol, str):
            return False
        import re
        pattern = r"^[A-Z]{1,5}(\.[A-Z])?$"
        return bool(re.match(pattern, symbol))

    async def get_spy_data(self):
        try:
            logger.debug("Fetching SPY data from Tradier API")
            data = await self._make_api_request(
                f"{self.tradier_base_url}/markets/quotes",
                params={"symbols": "SPY"},
                use_alpaca=False
            )
            logger.debug(f"Tradier API Response: {data}")
            quote = data["quotes"]["quote"]
            return {
                "candles": [{
                    "close": quote["last"],
                    "volume": quote["volume"],
                    "datetime": quote["trade_date"]
                }]
            }
        except Exception as e:
            logger.error(f"Error fetching SPY data: {str(e)}")
            return None

    async def get_price_history(self, symbol, period_type="day", period="1", frequency_type="minute", frequency=1):
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

            current_time = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
            if frequency_type.lower() == "minute":
                # Use Alpaca API for intraday data, but ensure data is at least 30 minutes delayed
                end_time = current_time - timedelta(minutes=30)
                start_time = end_time - timedelta(minutes=15)
                start_str_alpaca = start_time.isoformat()
                end_str_alpaca = end_time.isoformat()

                logger.debug(f"Fetching price history for {symbol} with interval {interval} using Alpaca API")
                alpaca_interval = f"{frequency}Min" if frequency in [1, 5, 15] else "5Min"
                params = {
                    "symbols": symbol,
                    "timeframe": alpaca_interval,
                    "start": start_str_alpaca,
                    "end": end_str_alpaca
                }
                alpaca_url = f"{self.alpaca_base_url.rstrip('/')}/v2/stocks/bars"
                data = await self._make_api_request(
                    alpaca_url,
                    params=params,
                    use_alpaca=True
                )
                logger.debug(f"Alpaca API Response: {data}")
                # Handle both possible structures: bars as a list or bars as a dict with symbol keys
                bars_data = data.get("bars", [])
                if isinstance(bars_data, dict):
                    bars = bars_data.get(symbol, [])
                else:
                    bars = bars_data
                if not bars or not isinstance(bars, list) or not all(isinstance(bar, dict) for bar in bars):
                    logger.warning(f"No valid timesales data available for {symbol} from Alpaca. Response: {data}")
                    return {"candles": []}

                candles = [
                    {
                        "close": bar["c"],
                        "volume": bar["v"],
                        "datetime": bar["t"]
                    }
                    for bar in bars
                ]
                return {"candles": candles}
            else:
                # Use Tradier for daily, weekly, monthly data
                end_date = current_time.astimezone(self.market_calendar.timezone).date()
                start_date = end_date - timedelta(days=int(period))
                start_str = start_date.strftime("%Y-%m-%d")
                end_str = end_date.strftime("%Y-%m-%d")

                logger.debug(f"Fetching price history for {symbol} with interval {interval} using Tradier history")
                data = await self._make_api_request(
                    f"{self.tradier_base_url}/markets/history",
                    params={
                        "symbol": symbol,
                        "interval": interval,
                        "start": start_str,
                        "end": end_str
                    },
                    use_alpaca=False
                )
                logger.debug(f"Tradier API Response: {data}")
                history = data.get("history", {}).get("day", [])
                if not history:
                    logger.warning(f"No history data available for {symbol}")
                    return {"candles": []}

                if isinstance(history, dict):
                    history = [history]

                candles = [
                    {
                        "close": day["close"],
                        "volume": day["volume"],
                        "datetime": day["date"]
                    }
                    for day in history
                ]
                return {"candles": candles}

        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {str(e)}")
            # Fallback: Use recent quote data to estimate trend
            try:
                quote_data = await self._make_api_request(
                    f"{self.tradier_base_url}/markets/quotes",
                    params={"symbols": symbol},
                    use_alpaca=False
                )
                quote = quote_data.get("quotes", {}).get("quote", {})
                if isinstance(quote, list):
                    quote = quote[0] if quote else {}
                last_price = quote.get("last", 0) or quote.get("close", 0)
                prev_close = quote.get("prevclose", 0) or last_price
                start_str = (current_time - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
                end_str = (current_time - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
                candles = [
                    {
                        "close": prev_close,
                        "volume": quote.get("volume", 0),
                        "datetime": quote.get("trade_date", start_str)
                    },
                    {
                        "close": last_price,
                        "volume": quote.get("volume", 0),
                        "datetime": quote.get("trade_date", end_str)
                    }
                ]
                return {"candles": candles}
            except Exception as fallback_err:
                logger.error(f"Fallback failed for {symbol}: {str(fallback_err)}")
                return {"candles": []}

    async def screen_stocks(self, symbols):
        if not symbols:
            return []

        valid_symbols = [symbol for symbol in symbols if self._validate_symbol(symbol)]
        if not valid_symbols:
            logger.error("No valid symbols provided for screening.")
            return []
        if len(valid_symbols) < len(symbols):
            invalid_symbols = set(symbols) - set(valid_symbols)
            logger.warning(f"Skipping invalid symbols for screening: {invalid_symbols}")

        results = []
        valid_symbols_str = ",".join(valid_symbols)
        logger.debug(f"Fetching quotes for symbols: {valid_symbols_str}")

        try:
            quote_data = await self._make_api_request(
                f"{self.tradier_base_url}/markets/quotes",
                params={"symbols": valid_symbols_str},
                use_alpaca=False
            )
            logger.debug(f"Tradier API Response: {quote_data}")
            quotes = quote_data.get("quotes", {}).get("quote", [])
            if quotes is None:
                logger.warning(f"No quote data available for {valid_symbols_str} (quotes is null).")
                return []

            if isinstance(quotes, dict):
                quotes = [quotes]

            market_caps = {}
            market_cap_tasks = [self._get_approximate_market_cap(symbol) for symbol in valid_symbols]
            market_cap_results = await asyncio.gather(*market_cap_tasks, return_exceptions=True)
            for symbol, market_cap in zip(valid_symbols, market_cap_results):
                if isinstance(market_cap, Exception):
                    logger.warning(f"Failed to fetch market cap for {symbol}: {str(market_cap)}")
                    market_caps[symbol] = 0
                else:
                    market_caps[symbol] = market_cap / 1000

            for quote in quotes:
                symbol = quote.get("symbol", "").split('.')[0].upper()
                if not symbol:
                    logger.warning(f"Invalid quote entry (missing symbol): {quote}")
                    continue

                price = quote.get("last", 0) or quote.get("close", 0) or 0
                prev_close = quote.get("prevclose", 0) or price or 0
                change = (price - prev_close) if prev_close else 0
                change_percentage = (change / prev_close * 100) if prev_close else 0
                volume = quote.get("volume", 0) or 0
                bid = quote.get("bid", 0) or 0
                ask = quote.get("ask", 0) or 0
                market_cap = market_caps.get(symbol, 0)

                results.append((symbol, price, change, volume, change_percentage, bid, ask, market_cap))
        except aiohttp.ClientResponseError as http_err:
            logger.error(f"HTTP Error fetching quotes for {valid_symbols_str} from Tradier: {str(http_err)}")
            logger.error(f"Status Code: {http_err.status}")
            logger.error(f"Response Text: {http_err.message}")
            return []
        except tenacity.RetryError as retry_err:
            logger.error(f"RetryError fetching quotes for {valid_symbols_str} from Tradier after all attempts: {str(retry_err)}")
            if retry_err.last_attempt and retry_err.last_attempt.failed:
                last_error = retry_err.last_attempt.exception()
                logger.error(f"Last error: {str(last_error)}")
                if isinstance(last_error, aiohttp.ClientResponseError):
                    logger.error(f"Status Code: {last_error.status}")
                    logger.error(f"Response Text: {last_error.message}")
                else:
                    logger.error("Last error is not a ClientResponseError.")
            else:
                logger.error("No last attempt information available.")
            return []
        except Exception as e:
            logger.error(f"Error fetching quotes for {valid_symbols_str} from Tradier: {str(e)}", exc_info=True)
            return []

        logger.debug(f"Screened stocks: {results}")
        return results

    async def get_buy_sell_volume(self, symbols, bid_ask_data=None, force_refresh=False):
        if not symbols:
            return {}

        valid_symbols = [symbol for symbol in symbols if self._validate_symbol(symbol)]
        if not valid_symbols:
            logger.error("No valid symbols provided for buy/sell volume.")
            return {}
        if len(valid_symbols) < len(symbols):
            invalid_symbols = set(symbols) - set(valid_symbols)
            logger.warning(f"Skipping invalid symbols for buy/sell volume: {invalid_symbols}")

        results = {}
        current_time = time.time()
        valid_symbols_to_fetch = []

        if not force_refresh:
            for symbol in valid_symbols:
                if symbol in self.buy_sell_cache:
                    cached_data = self.buy_sell_cache[symbol]
                    if current_time - cached_data["timestamp"] < self.cache_ttl:
                        results[symbol] = (cached_data["buy_volume"], cached_data["sell_volume"])
                        logger.debug(f"Using cached buy/sell volume for {symbol}: {results[symbol]}")
                        continue
                valid_symbols_to_fetch.append(symbol)
        else:
            logger.debug("Force refresh enabled; bypassing cache for all symbols")
            valid_symbols_to_fetch = valid_symbols
            for symbol in valid_symbols:
                self.buy_sell_cache.pop(symbol, None)

        if not valid_symbols_to_fetch:
            return results

        if bid_ask_data is None:
            bid_ask_data = {}
            valid_symbols_str = ",".join(valid_symbols_to_fetch)
            logger.debug(f"Fetching bid/ask for symbols in a single batch: {valid_symbols_str}")
            try:
                quote_data = await self._make_api_request(
                    f"{self.tradier_base_url}/markets/quotes",
                    params={"symbols": valid_symbols_str},
                    use_alpaca=False
                )
                quotes = quote_data.get("quotes", {}).get("quote", {})
                if isinstance(quotes, dict):
                    quotes = [quotes]
                for quote in quotes:
                    symbol = quote["symbol"].split('.')[0].upper()
                    bid = quote.get("bid", 0)
                    ask = quote.get("ask", 0)
                    last_price = quote.get("last", 0) or quote.get("close", 0)
                    if bid == 0 or ask == 0:
                        bid = last_price * 0.995
                        ask = last_price * 1.005
                    bid_ask_data[symbol] = (bid, ask)
            except Exception as e:
                logger.error(f"Error fetching bid/ask data for {valid_symbols_str}: {str(e)}")
                for symbol in valid_symbols_to_fetch:
                    stock_data = await self.screen_stocks([symbol])
                    last_price = stock_data[0][1] if stock_data else 0
                    bid = last_price * 0.995
                    ask = last_price * 1.005
                    bid_ask_data[symbol] = (bid, ask)

        total_volumes = {}
        stock_data = await self.screen_stocks(symbols=valid_symbols_to_fetch)
        for stock in stock_data:
            symbol = stock[0]
            total_volume = stock[3]
            total_volumes[symbol] = total_volume

        current_time_dt = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        current_time_eastern = current_time_dt.astimezone(self.market_calendar.timezone)
        current_date = current_time_eastern.date()
        is_market_open = self.market_calendar.is_market_open(current_time_dt)

        if is_market_open:
            end_time = current_time_dt - timedelta(minutes=30)
            start_time = end_time - timedelta(minutes=15)
        else:
            previous_trading_day = self.market_calendar.get_previous_trading_day(current_date)
            market_open_utc, market_close_utc = self.market_calendar.get_market_hours(
                previous_trading_day,
                market_open_hour=Config.MARKET_OPEN_HOUR,
                market_open_minute=Config.MARKET_OPEN_MINUTE,
                market_close_hour=Config.MARKET_CLOSE_HOUR,
                market_close_minute=Config.MARKET_CLOSE_MINUTE
            )
            end_time = market_close_utc - timedelta(minutes=1)
            start_time = end_time - timedelta(minutes=15)

        start_ts = start_time.isoformat()
        end_ts = end_time.isoformat()
        logger.debug(f"Time range for buy/sell volume: start={start_ts}, end={end_ts}")

        price_trends = {}
        for symbol in valid_symbols_to_fetch:
            try:
                history_data = await self.get_price_history(
                    symbol,
                    period_type="day",
                    period="1",
                    frequency_type="minute",
                    frequency=5
                )
                if history_data and "candles" in history_data:
                    candles = history_data["candles"][-12:]
                    if len(candles) >= 2:
                        prices = [candle["close"] for candle in candles]
                        sma_short = sum(prices[-3:]) / 3
                        sma_long = sum(prices[:3]) / 3
                        trend = 1 if sma_short > sma_long else -1 if sma_short < sma_long else 0
                        price_trends[symbol] = trend
                    else:
                        price_trends[symbol] = 0
                else:
                    price_trends[symbol] = 0
            except Exception as e:
                logger.error(f"Error fetching price history for trend analysis of {symbol}: {str(e)}")
                price_trends[symbol] = 0

        trades_by_symbol = defaultdict(list)
        if valid_symbols_to_fetch:
            async def fetch_timesales(symbol):
                logger.debug(f"Fetching timesales for {symbol} from Alpaca API")
                params = {
                    "symbols": symbol,
                    "timeframe": "1Min",
                    "start": start_ts,
                    "end": end_ts
                }
                logger.debug(f"Alpaca timesales request parameters for {symbol}: {params}")
                try:
                    alpaca_url = f"{self.alpaca_base_url.rstrip('/')}/v2/stocks/bars"
                    data = await self._make_api_request(
                        alpaca_url,
                        params=params,
                        use_alpaca=True
                    )
                    logger.debug(f"Alpaca API Response for {symbol}: {data}")
                    # Handle both possible structures: bars as a list or bars as a dict with symbol keys
                    bars_data = data.get("bars", [])
                    if isinstance(bars_data, dict):
                        bars = bars_data.get(symbol, [])
                    else:
                        bars = bars_data
                    if not bars or not isinstance(bars, list) or not all(isinstance(bar, dict) for bar in bars):
                        logger.warning(f"No valid trade data available for {symbol} from Alpaca. Response: {data}")
                        return symbol, []
                    trades = [
                        {
                            "price": bar["c"],
                            "volume": bar["v"],
                            "time": bar["t"]
                        }
                        for bar in bars
                    ]
                    return symbol, trades
                except Exception as e:
                    logger.error(f"Error fetching timesales for {symbol} from Alpaca: {str(e)}")
                    return symbol, []

            timesales_results = await asyncio.gather(
                *[fetch_timesales(symbol) for symbol in valid_symbols_to_fetch],
                return_exceptions=True
            )

            for result in timesales_results:
                if isinstance(result, tuple):
                    symbol, trades = result
                    if trades:
                        trades_by_symbol[symbol] = trades
                    else:
                        logger.warning(f"No trade data available for {symbol}. Falling back to trend-based split.")
                        total_volume = total_volumes.get(symbol, 0)
                        trend = price_trends.get(symbol, 0)
                        if trend > 0:
                            buy_volume = int(total_volume * 0.6)
                            sell_volume = total_volume - buy_volume
                        elif trend < 0:
                            buy_volume = int(total_volume * 0.4)
                            sell_volume = total_volume - buy_volume
                        else:
                            buy_volume = total_volume // 2
                            sell_volume = total_volume - buy_volume
                        results[symbol] = (buy_volume, sell_volume)
                        self.buy_sell_cache[symbol] = {
                            "buy_volume": buy_volume,
                            "sell_volume": sell_volume,
                            "timestamp": current_time
                        }
                else:
                    logger.error(f"Unexpected result from timesales fetch: {result}")

        try:
            sentiment_scores = await self.stock_sentiment.get_stock_sentiment_batch(valid_symbols_to_fetch)
        except Exception as e:
            logger.error(f"Error fetching sentiment for symbols: {str(e)}")
            if isinstance(e, AttributeError):
                logger.error("StockSentiment does not have get_stock_sentiment_batch method.")
            sentiment_scores = {symbol: 0 for symbol in valid_symbols_to_fetch}

        for symbol in valid_symbols_to_fetch:
            trades = trades_by_symbol.get(symbol, [])
            bid, ask = bid_ask_data.get(symbol, (0, 0))
            trend = price_trends.get(symbol, 0)

            if bid == 0 or ask == 0:
                logger.warning(f"No valid bid/ask data for {symbol}. Using trend-based split.")
                total_volume = total_volumes.get(symbol, 0)
                if trend > 0:
                    buy_volume = int(total_volume * 0.6)
                    sell_volume = total_volume - buy_volume
                elif trend < 0:
                    buy_volume = int(total_volume * 0.4)
                    sell_volume = total_volume - buy_volume
                else:
                    buy_volume = total_volume // 2
                    sell_volume = total_volume - buy_volume
                results[symbol] = (buy_volume, sell_volume)
                self.buy_sell_cache[symbol] = {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "timestamp": current_time
                }
                continue

            if not trades:
                logger.warning(f"No trade data available for {symbol}. Using trend-based split.")
                total_volume = total_volumes.get(symbol, 0)
                if trend > 0:
                    buy_volume = int(total_volume * 0.6)
                    sell_volume = total_volume - buy_volume
                elif trend < 0:
                    buy_volume = int(total_volume * 0.4)
                    sell_volume = total_volume - buy_volume
                else:
                    buy_volume = total_volume // 2
                    sell_volume = total_volume - buy_volume
                results[symbol] = (buy_volume, sell_volume)
                self.buy_sell_cache[symbol] = {
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "timestamp": current_time
                }
                continue

            sentiment_score = sentiment_scores.get(symbol, 0)
            buy_volume = 0
            sell_volume = 0
            recent_buys = 0
            recent_sells = 0
            momentum_window = 20

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
                    momentum_buy_ratio = recent_buys / total_recent if total_recent > 0 else 0.5

                    trend_adjustment = 0.6 if trend > 0 else 0.4 if trend < 0 else 0.5
                    sentiment_adjustment = (sentiment_score + 1) / 2
                    buy_ratio = (0.5 * momentum_buy_ratio + 0.3 * trend_adjustment + 0.2 * sentiment_adjustment)
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

    async def _get_approximate_market_cap(self, symbol):
        try:
            logger.debug(f"Fetching market cap for {symbol} using yfinance")
            loop = asyncio.get_running_loop()
            ticker = yf.Ticker(symbol)
            info = await loop.run_in_executor(None, lambda: ticker.info)
            market_cap = info.get("marketCap", 0)
            market_cap_millions = market_cap / 1e6
            return market_cap_millions
        except Exception as e:
            logger.error(f"Error fetching market cap for {symbol} using yfinance: {str(e)}")
            return 0

    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s"))
    logger.addHandler(handler)