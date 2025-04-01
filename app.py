from flask import Flask, request, jsonify
import logging
import time
from flask_app.data.marketdata import MarketData
from flask_app.config import Config

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize MarketData
market_data = MarketData()

# In-memory cache for quotes
quotes_cache = {}
CACHE_TTL = 10  # Cache time-to-live in seconds

@app.route('/api/screen', methods=['POST'])
def screen_stocks():
    """Screen stocks based on given criteria."""
    try:
        data = request.get_json()
        logger.debug(f"Received screening request: {data}")
        symbols = data.get('symbols', [])
        min_price = data.get('min_price', 0)
        max_price = data.get('max_price', 1e9)
        min_volume = data.get('min_volume', 0)
        market_cap_filter = data.get('market_cap_filter', 'Any')

        filtered_stocks = market_data.screen_stocks(
            symbols=symbols,
            min_price=min_price,
            max_price=max_price,
            min_volume=min_volume,
            market_cap_filter=market_cap_filter
        )
        logger.debug(f"Filtered stocks: {filtered_stocks}")
        return jsonify(filtered_stocks)
    except Exception as e:
        logger.error(f"Error in screen_stocks: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_quotes', methods=['POST'])
def update_quotes():
    """Fetch updated price, volume, and change percentage for a list of symbols with caching."""
    try:
        data = request.get_json()
        logger.debug(f"Received update quotes request: {data}")
        symbols = data.get('symbols', [])

        if not symbols:
            return jsonify({"error": "No symbols provided"}), 400

        # Create a cache key based on the sorted list of symbols
        cache_key = ",".join(sorted(symbols))
        current_time = time.time()

        # Check if the data is in the cache and not expired
        if cache_key in quotes_cache:
            cached_data = quotes_cache[cache_key]
            if current_time - cached_data["timestamp"] < CACHE_TTL:
                logger.debug(f"Returning cached data for symbols: {cache_key}")
                return jsonify(cached_data["data"])

        # Fetch updated quotes using MarketData
        updated_quotes = market_data.screen_stocks(symbols=symbols)
        logger.debug(f"Updated quotes: {updated_quotes}")

        # Format the response as a dictionary for easier lookup in the frontend
        quote_data = {}
        for quote in updated_quotes:
            symbol, price, _, volume, change_percentage = quote
            quote_data[symbol] = {
                "price": price,
                "volume": volume,
                "change_percentage": change_percentage
            }

        # Store the result in the cache with a timestamp
        quotes_cache[cache_key] = {
            "data": quote_data,
            "timestamp": current_time
        }

        # Optional: Clean up old cache entries (to prevent memory growth)
        for key in list(quotes_cache.keys()):
            if current_time - quotes_cache[key]["timestamp"] >= CACHE_TTL:
                del quotes_cache[key]

        return jsonify(quote_data)
    except Exception as e:
        logger.error(f"Error in update_quotes: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)