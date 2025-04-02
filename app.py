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
        # Log the raw request body for debugging
        raw_data = request.get_data(as_text=True)
        logger.debug(f"Raw request body: {raw_data}")

        # Attempt to parse the request body as JSON
        data = request.get_json(force=True)  # Force parsing even if Content-Type is not set
        if not isinstance(data, dict):
            logger.error(f"Request body is not a valid JSON object: {data}")
            return jsonify({"error": "Invalid JSON: Request body must be a JSON object"}), 400

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

        # Prepare bid/ask data to pass to get_buy_sell_volume
        bid_ask_data = {stock[0]: (stock[5], stock[6]) for stock in filtered_stocks}

        # Batch fetch buy/sell volume for all symbols, forcing a refresh for new stocks
        buy_sell_volumes = market_data.get_buy_sell_volume(
            symbols=[stock[0] for stock in filtered_stocks],
            bid_ask_data=bid_ask_data,
            force_refresh=True  # Always fetch fresh data for screening
        )

        # Add buy_volume and sell_volume to each stock tuple
        updated_stocks = []
        for stock in filtered_stocks:
            symbol = stock[0]
            buy_volume, sell_volume = buy_sell_volumes.get(symbol, (0, 0))
            updated_stock = (symbol, stock[1], stock[2], stock[3], stock[4], buy_volume, sell_volume)
            updated_stocks.append(updated_stock)

        logger.debug(f"Filtered stocks with buy/sell volume: {updated_stocks}")
        return jsonify(updated_stocks)
    except ValueError as ve:
        logger.error(f"Failed to parse JSON request body: {str(ve)}")
        return jsonify({"error": "Invalid JSON format in request body"}), 400
    except Exception as e:
        logger.error(f"Error in screen_stocks: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_quotes', methods=['POST'])
def update_quotes():
    """Fetch updated price, volume, and change percentage for a list of symbols with caching."""
    try:
        # Log the raw request body for debugging
        raw_data = request.get_data(as_text=True)
        logger.debug(f"Raw request body: {raw_data}")

        # Attempt to parse the request body as JSON
        data = request.get_json(force=True)  # Force parsing even if Content-Type is not set
        if not isinstance(data, dict):
            logger.error(f"Request body is not a valid JSON object: {data}")
            return jsonify({"error": "Invalid JSON: Request body must be a JSON object"}), 400

        logger.debug(f"Received update quotes request: {data}")
        symbols = data.get('symbols', [])
        force_refresh = data.get('force_refresh', False)  # Allow frontend to request a refresh

        if not symbols:
            return jsonify({"error": "No symbols provided"}), 400

        # Create a cache key based on the sorted list of symbols
        cache_key = ",".join(sorted(symbols))
        current_time = time.time()

        # Check if the data is in the cache and not expired (unless force_refresh is True)
        if not force_refresh and cache_key in quotes_cache:
            cached_data = quotes_cache[cache_key]
            if current_time - cached_data["timestamp"] < CACHE_TTL:
                logger.debug(f"Returning cached data for symbols: {cache_key}")
                return jsonify(cached_data["data"])

        # Fetch updated quotes using MarketData
        updated_quotes = market_data.screen_stocks(symbols=symbols)
        logger.debug(f"Updated quotes: {updated_quotes}")

        # Prepare bid/ask data to pass to get_buy_sell_volume
        bid_ask_data = {stock[0]: (stock[5], stock[6]) for stock in updated_quotes}

        # Batch fetch buy/sell volume for all symbols
        buy_sell_volumes = market_data.get_buy_sell_volume(
            symbols=[stock[0] for stock in updated_quotes],
            bid_ask_data=bid_ask_data,
            force_refresh=force_refresh  # Respect the force_refresh parameter
        )

        # Format the response as a dictionary for easier lookup in the frontend
        quote_data = {}
        for quote in updated_quotes:
            symbol = quote[0]
            buy_volume, sell_volume = buy_sell_volumes.get(symbol, (0, 0))
            quote_data[symbol] = {
                "price": quote[1],
                "volume": quote[3],
                "change_percentage": quote[4],
                "volume_bought": buy_volume,
                "volume_sold": sell_volume
            }

        # Store the result in the cache with a timestamp
        quotes_cache[cache_key] = {
            "data": quote_data,
            "timestamp": current_time
        }

        # Clean up old cache entries
        for key in list(quotes_cache.keys()):
            if current_time - quotes_cache[key]["timestamp"] >= CACHE_TTL:
                del quotes_cache[key]

        return jsonify(quote_data)
    except ValueError as ve:
        logger.error(f"Failed to parse JSON request body: {str(ve)}")
        return jsonify({"error": "Invalid JSON format in request body"}), 400
    except Exception as e:
        logger.error(f"Error in update_quotes: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)

if __name__ == "__main__":
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)