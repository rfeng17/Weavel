import time
import aiohttp
import asyncio
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import tenacity
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from flask_app import logger

class StockSentiment:
    def __init__(self, alpaca_base_url, alpaca_headers, rate_limit_per_second):
        """
        Initialize the StockSentiment class for fetching and analyzing stock news sentiment.
        Args:
            alpaca_base_url: Base URL for Alpaca API.
            alpaca_headers: Headers for Alpaca API requests (with API key and secret).
            rate_limit_per_second: Rate limit for Alpaca API requests (default: 3.33 requests/sec).
        """
        self.alpaca_base_url = alpaca_base_url
        self.alpaca_headers = alpaca_headers
        self.rate_limit_per_second = rate_limit_per_second
        self.last_request_time = 0
        self.lock = asyncio.Lock()  # Changed from threading.Lock to asyncio.Lock
        self.sentiment_analyzer = SentimentIntensityAnalyzer()

    async def _rate_limit(self):
        """Enforce rate limiting for Alpaca API requests in an async context."""
        async with self.lock:  # Use async context manager for asyncio.Lock
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            sleep_time = (1 / self.rate_limit_per_second) - time_since_last
            if sleep_time > 0:
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
                await asyncio.sleep(sleep_time)
            self.last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(aiohttp.ClientResponseError),
        before_sleep=lambda retry_state: logger.debug(f"Retrying API request (attempt {retry_state.attempt_number})...")
    )
    async def _make_api_request(self, url, params):
        """Make an async API request to Alpaca with rate limiting and retry logic."""
        await self._rate_limit()
        async with aiohttp.ClientSession(headers=self.alpaca_headers) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()

    def _validate_symbol(self, symbol):
        """Validate the stock symbol."""
        if not isinstance(symbol, str) or not symbol:
            return False
        # Basic validation: ensure the symbol contains only letters, numbers, and certain characters
        return bool(symbol.isalnum() or '-' in symbol or '.' in symbol)

    def _validate_symbols(self, symbols):
        """Validate a list of stock symbols."""
        if not symbols:
            return False
        return all(self._validate_symbol(symbol) for symbol in symbols)

    async def get_stock_sentiment(self, symbol):
        """
        Fetch recent news for a stock from Alpaca and compute a sentiment score.
        Args:
            symbol: Stock symbol (e.g., "MSFT").
        Returns:
            Sentiment score between -1 (negative) and +1 (positive), or 0 if no data.
        """
        # Validate the symbol before making the API call
        if not self._validate_symbol(symbol):
            logger.warning(f"Invalid symbol {symbol} for sentiment analysis. Using neutral sentiment.")
            return 0.0

        try:
            # Use a historical time range: last 7 days up to the current time
            current_time_dt = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
            news_end_time = current_time_dt
            news_start_time = current_time_dt - timedelta(days=7)

            # Format timestamps for Alpaca
            start_ts = news_start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_ts = news_end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.debug(f"Fetching news for {symbol} from {start_ts} to {end_ts}")

            # Fetch news from Alpaca
            news_data = await self._make_api_request(
                f"{self.alpaca_base_url}/v1beta1/news",
                params={
                    "symbols": symbol,
                    "start": start_ts,
                    "end": end_ts,
                    "limit": 50  # Fetch up to 50 news articles
                }
            )

            if not news_data or "news" not in news_data:
                logger.warning(f"No news data available for {symbol} in the specified time range.")
                return 0.0

            # Analyze sentiment of news headlines and summaries
            sentiment_scores = []
            for article in news_data["news"]:
                text = article.get("headline", "") + " " + article.get("summary", "")
                if not text.strip():
                    continue
                sentiment = self.sentiment_analyzer.polarity_scores(text)
                sentiment_scores.append(sentiment["compound"])

            if not sentiment_scores:
                logger.warning(f"No valid news text found for {symbol}. Using neutral sentiment.")
                return 0.0

            # Average the sentiment scores
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)
            logger.debug(f"Computed sentiment score for {symbol}: {avg_sentiment}")
            return avg_sentiment

        except aiohttp.ClientResponseError as http_err:
            logger.error(f"HTTP Error fetching news for {symbol} from Alpaca: {str(http_err)}")
            logger.error(f"Status Code: {http_err.status}")
            logger.error(f"Response Text: {http_err.message}")
            return 0.0
        except tenacity.RetryError as retry_err:
            logger.error(f"RetryError fetching news for {symbol} from Alpaca after all attempts: {str(retry_err)}")
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
            return 0.0
        except Exception as e:
            logger.error(f"Unexpected error computing sentiment for {symbol}: {str(e)}")
            return 0.0
        
    async def get_stock_sentiment_batch(self, symbols):
        """
        Fetch recent news for multiple stocks from Alpaca and compute sentiment scores.
        Args:
            symbols: List of stock symbols (e.g., ["MSFT", "AAPL"]).
        Returns:
            Dictionary mapping symbols to sentiment scores (between -1 and +1), or 0 if no data.
        """
        # Validate symbols
        if not self._validate_symbols(symbols):
            logger.warning(f"Invalid symbols {symbols} for sentiment analysis. Using neutral sentiment.")
            return {symbol: 0.0 for symbol in symbols}

        try:
            # Use a historical time range: last 7 days up to the current time
            current_time_dt = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
            news_end_time = current_time_dt
            news_start_time = current_time_dt - timedelta(days=7)

            # Format timestamps for Alpaca
            start_ts = news_start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_ts = news_end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            symbols_str = ",".join(symbols)
            logger.debug(f"Fetching news for symbols {symbols_str} from {start_ts} to {end_ts}")

            # Fetch news from Alpaca for all symbols in a single request
            news_data = await self._make_api_request(
                f"{self.alpaca_base_url}/v1beta1/news",
                params={
                    "symbols": symbols_str,
                    "start": start_ts,
                    "end": end_ts,
                    "limit": 10  # Reduced from 50 to 10 to speed up processing
                }
            )

            if not news_data or "news" not in news_data:
                logger.warning(f"No news data available for symbols {symbols_str} in the specified time range.")
                return {symbol: 0.0 for symbol in symbols}

            # Group news articles by symbol
            news_by_symbol = {symbol: [] for symbol in symbols}
            for article in news_data["news"]:
                article_symbols = article.get("symbols", [])
                for symbol in article_symbols:
                    if symbol in news_by_symbol:
                        news_by_symbol[symbol].append(article)

            # Compute sentiment for each symbol
            sentiment_scores = {}
            for symbol in symbols:
                articles = news_by_symbol[symbol]
                if not articles:
                    logger.warning(f"No news articles found for {symbol}. Using neutral sentiment.")
                    sentiment_scores[symbol] = 0.0
                    continue

                sentiment_scores_list = []
                for article in articles:
                    text = article.get("headline", "") + " " + article.get("summary", "")
                    if not text.strip():
                        continue
                    sentiment = self.sentiment_analyzer.polarity_scores(text)
                    sentiment_scores_list.append(sentiment["compound"])

                if not sentiment_scores_list:
                    logger.warning(f"No valid news text found for {symbol}. Using neutral sentiment.")
                    sentiment_scores[symbol] = 0.0
                else:
                    avg_sentiment = sum(sentiment_scores_list) / len(sentiment_scores_list)
                    logger.debug(f"Computed sentiment score for {symbol}: {avg_sentiment}")
                    sentiment_scores[symbol] = avg_sentiment

            return sentiment_scores
        except aiohttp.ClientResponseError as http_err:
            logger.error(f"HTTP Error fetching news for symbols {symbols_str} from Alpaca: {str(http_err)}")
            logger.error(f"Status Code: {http_err.status}")
            logger.error(f"Response Text: {http_err.message}")
            return {symbol: 0.0 for symbol in symbols}
        except tenacity.RetryError as retry_err:
            logger.error(f"RetryError fetching news for symbols {symbols_str} from Alpaca after all attempts: {str(retry_err)}")
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
            return {symbol: 0.0 for symbol in symbols}
        except Exception as e:
            logger.error(f"Unexpected error computing sentiment for symbols {symbols_str}: {str(e)}")
            return {symbol: 0.0 for symbol in symbols}