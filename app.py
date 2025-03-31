from flask import Flask, jsonify, request
from flask_app.data.marketdata import MarketData
import logging

app = Flask(__name__)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize MarketData
market_data = MarketData()

@app.route('/api/spy', methods=['GET'])
def get_spy_data():
    """Fetch SPY market data."""
    try:
        data = market_data.get_spy_data()
        if data is None:
            return jsonify({"error": "Failed to fetch SPY data"}), 500
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error in /api/spy: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/screen', methods=['POST'])
def screen_stocks():
    """Screen stocks based on criteria."""
    try:
        data = request.get_json()
        symbols = data.get("symbols", [])
        min_price = data.get("min_price", 0)
        max_price = data.get("max_price", float('inf'))
        min_volume = data.get("min_volume", 0)
        market_cap_filter = data.get("market_cap_filter", "Any")

        filtered_stocks = market_data.screen_stocks(
            symbols=symbols,
            min_price=min_price,
            max_price=max_price,
            min_volume=min_volume,
            market_cap_filter=market_cap_filter
        )
        return jsonify(filtered_stocks)
    except Exception as e:
        logger.error(f"Error in /api/screen: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/price_history/<symbol>', methods=['GET'])
def get_price_history(symbol):
    """Fetch price history for a given symbol."""
    try:
        period_type = request.args.get("period_type", "day")
        period = request.args.get("period", "1")
        frequency_type = request.args.get("frequency_type", "minute")
        frequency = int(request.args.get("frequency", 1))

        data = market_data.get_price_history(
            symbol=symbol,
            period_type=period_type,
            period=period,
            frequency_type=frequency_type,
            frequency=frequency
        )
        if data is None:
            return jsonify({"error": f"Failed to fetch price history for {symbol}"}), 500
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error in /api/price_history: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)