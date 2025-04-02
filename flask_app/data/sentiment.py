import time
import requests
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import tenacity
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from flask_app import logger
import threading

class StockSentiment:
    def __init__(self, alpaca_base_url, alpaca_headers, rate_limit_per_second=3.33):
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
        self.lock = threading.Lock()
        self.sentiment_analyzer = SentimentIntensityAnalyzer()

    def _rate_limit(self):
        """Enforce rate limiting for Alpaca API requests."""
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
    def _make_api_request(self, url, params):
        """Make an API request to Alpaca with rate limiting and retry logic."""
        self._rate_limit()
        response = requests.get(url, headers=self.alpaca_headers, params=params)
        response.raise_for_status()
        return response

    def _validate_symbol(self, symbol):
        """Validate the stock symbol."""
        if not isinstance(symbol, str) or not symbol:
            return False
        # Basic validation: ensure the symbol contains only letters, numbers, and certain characters
        return bool(symbol.isalnum() or '-' in symbol or '.' in symbol)

    def get_stock_sentiment(self, symbol):
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
            response = self._make_api_request(
                f"{self.alpaca_base_url}/v1beta1/news",
                params={
                    "symbols": symbol,
                    "start": start_ts,
                    "end": end_ts,
                    "limit": 50  # Fetch up to 50 news articles
                }
            )
            news_data = response.json()

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

        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error fetching news for {symbol} from Alpaca: {str(http_err)}")
            logger.error(f"Status Code: {http_err.response.status_code if http_err.response else 'N/A'}")
            logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
            return 0.0
        except tenacity.RetryError as retry_err:
            logger.error(f"RetryError fetching news for {symbol} from Alpaca after all attempts: {str(retry_err)}")
            if retry_err.last_attempt and retry_err.last_attempt.failed:
                last_error = retry_err.last_attempt.exception()
                logger.error(f"Last error: {str(last_error)}")
                if isinstance(last_error, requests.exceptions.HTTPError):
                    logger.error(f"Status Code: {last_error.response.status_code if last_error.response else 'N/A'}")
                    logger.error(f"Response Text: {last_error.response.text if last_error.response else 'No response'}")
                else:
                    logger.error("Last error is not an HTTPError.")
            else:
                logger.error("No last attempt information available.")
            return 0.0
        except Exception as e:
            logger.error(f"Unexpected error computing sentiment for {symbol}: {str(e)}")
            return 0.0