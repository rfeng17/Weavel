from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import logging
import time
import asyncio
from flask_app.data.marketdata import MarketData
from flask_app.config import Config

app = FastAPI()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Initialize MarketData
market_data = MarketData()

# In-memory caches
stock_cache = {}
volume_cache = {}

# Configuration constants
CACHE_TTL = 10  # Cache time-to-live in seconds
MAX_SYMBOLS = 50  # Maximum number of symbols per request
MAX_REQUESTS_PER_MINUTE = 60  # Rate limit: requests per minute per client
request_counts = {}  # Track requests per client IP for rate limiting

def rate_limit(client_ip: str):
    """
    Enforce rate limiting based on client IP.
    Args:
        client_ip: The client's IP address.
    Returns:
        Tuple of (allowed: bool, error_message: str or None).
    """
    current_time = time.time()
    # Clean up old entries
    for ip in list(request_counts.keys()):
        if current_time - request_counts[ip][1] > 60:
            del request_counts[ip]
    
    if client_ip in request_counts:
        count, timestamp = request_counts[client_ip]
        if current_time - timestamp < 60:
            if count >= MAX_REQUESTS_PER_MINUTE:
                return False, "Rate limit exceeded. Please try again later."
            request_counts[client_ip] = (count + 1, timestamp)
        else:
            request_counts[client_ip] = (1, current_time)
    else:
        request_counts[client_ip] = (1, current_time)
    return True, None

@app.post("/api/update_quotes")
async def update_quotes(request: Request):
    """
    Fetch updated price, volume, and change percentage for a list of symbols with caching.
    """
    try:
        # Rate limiting
        client_ip = request.client.host
        allowed, error_message = rate_limit(client_ip)
        if not allowed:
            logger.warning(f"Rate limit exceeded for client {client_ip}")
            raise HTTPException(status_code=429, detail=error_message)

        # Log the raw request body for debugging
        raw_data = await request.body()
        logger.debug(f"Raw request body: {raw_data.decode('utf-8')}")

        # Parse the request body as JSON
        data = await request.json()
        if not isinstance(data, dict):
            logger.error(f"Request body is not a valid JSON object: {data}")
            raise HTTPException(status_code=400, detail="Invalid JSON: Request body must be a JSON object")

        logger.debug(f"Received update quotes request: {data}")
        symbols = data.get('symbols', [])
        force_refresh = data.get('force_refresh', False)

        # Validate the number of symbols
        if not symbols:
            raise HTTPException(status_code=400, detail="No symbols provided")
        if len(symbols) > MAX_SYMBOLS:
            logger.warning(f"Too many symbols requested: {len(symbols)} by client {client_ip}")
            raise HTTPException(status_code=400, detail=f"Too many symbols. Maximum allowed is {MAX_SYMBOLS}")

        current_time = time.time()
        # Check cache for existing stock data
        cache_key = ",".join(sorted(symbols))
        if not force_refresh and cache_key in stock_cache:
            cached_data = stock_cache[cache_key]
            if current_time - cached_data["timestamp"] < CACHE_TTL:
                logger.debug(f"Returning cached stock data for symbols: {cache_key}")
                updated_quotes = cached_data["data"]
            else:
                logger.debug(f"Cache expired for symbols: {cache_key}")
                del stock_cache[cache_key]
                updated_quotes = []
        else:
            updated_quotes = []

        # Fetch updated quotes if not in cache or force_refresh is True
        if not updated_quotes:
            start_time = time.time()
            updated_quotes = await market_data.screen_stocks(symbols)
            logger.debug(f"screen_stocks took {time.time() - start_time:.2f} seconds")
            if not updated_quotes:
                logger.error("Failed to fetch updated quotes from MarketData")
                raise HTTPException(status_code=500, detail="Failed to fetch updated quotes")
            # Cache the raw stock data
            stock_cache[cache_key] = {
                "data": updated_quotes,
                "timestamp": current_time
            }

        # Validate updated_quotes: ensure it's a list of tuples with 8 elements
        validated_quotes = []
        for quote in updated_quotes:
            if not isinstance(quote, tuple):
                logger.warning(f"Invalid quote entry (not a tuple): {quote}")
                continue
            if len(quote) != 8:  # Updated to expect 8 elements
                logger.warning(f"Invalid quote tuple (wrong length, expected 8): {quote}")
                continue
            if not isinstance(quote[0], str):
                logger.warning(f"Invalid quote tuple (symbol is not a string): {quote}")
                continue
            validated_quotes.append(quote)

        if not validated_quotes:
            logger.warning("No valid quotes after validation.")
            return {}

        # Prepare bid/ask data to pass to get_buy_sell_volume
        bid_ask_data = {quote[0]: (quote[5], quote[6]) for quote in validated_quotes}
        symbols_to_fetch = [quote[0] for quote in validated_quotes]

        # Check cache for buy/sell volumes
        volume_cache_key = ",".join(sorted(symbols_to_fetch))
        if not force_refresh and volume_cache_key in volume_cache:
            cached_volumes = volume_cache[volume_cache_key]
            if current_time - cached_volumes["timestamp"] < CACHE_TTL:
                logger.debug(f"Returning cached buy/sell volumes for symbols: {volume_cache_key}")
                buy_sell_volumes = cached_volumes["data"]
            else:
                logger.debug(f"Volume cache expired for symbols: {volume_cache_key}")
                del volume_cache[volume_cache_key]
                buy_sell_volumes = None
        else:
            buy_sell_volumes = None

        # Fetch buy/sell volumes if not in cache or force_refresh is True
        if buy_sell_volumes is None:
            start_time = time.time()
            buy_sell_volumes = await market_data.get_buy_sell_volume(
                symbols=symbols_to_fetch,
                bid_ask_data=bid_ask_data,
                force_refresh=force_refresh
            )
            logger.debug(f"get_buy_sell_volume took {time.time() - start_time:.2f} seconds")
            if buy_sell_volumes is None:
                logger.error("Failed to fetch buy/sell volumes from MarketData")
                buy_sell_volumes = {symbol: (0, 0) for symbol in symbols_to_fetch}
            # Cache the volumes
            volume_cache[volume_cache_key] = {
                "data": buy_sell_volumes,
                "timestamp": current_time
            }

        # Format the response as a dictionary for easier lookup in the frontend
        quote_data = {}
        for quote in validated_quotes:
            symbol = quote[0]
            buy_volume, sell_volume = buy_sell_volumes.get(symbol, (0, 0))
            quote_data[symbol] = {
                "price": quote[1],
                "volume": quote[3],
                "change_percentage": quote[4],
                "market_cap": quote[7],  # Added market cap
                "volume_bought": buy_volume,
                "volume_sold": sell_volume
            }

        # Clean up old cache entries
        for key in list(stock_cache.keys()):
            if current_time - stock_cache[key]["timestamp"] >= CACHE_TTL:
                del stock_cache[key]
        for key in list(volume_cache.keys()):
            if current_time - volume_cache[key]["timestamp"] >= CACHE_TTL:
                del volume_cache[key]

        return quote_data
    except ValueError as ve:
        logger.error(f"Failed to parse JSON request body: {str(ve)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format in request body")
    except Exception as e:
        logger.error(f"Error in update_quotes: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/screen")
async def screen_stocks(request: Request):
    """
    Screen stocks based on a list of symbols and return basic stock data.
    """
    try:
        # Rate limiting
        client_ip = request.client.host
        allowed, error_message = rate_limit(client_ip)
        if not allowed:
            logger.warning(f"Rate limit exceeded for client {client_ip}")
            raise HTTPException(status_code=429, detail=error_message)

        # Log the raw request body for debugging
        raw_data = await request.body()
        logger.debug(f"Raw request body: {raw_data.decode('utf-8')}")

        # Parse the request body as JSON
        data = await request.json()
        if not isinstance(data, dict):
            logger.error(f"Request body is not a valid JSON object: {data}")
            raise HTTPException(status_code=400, detail="Invalid JSON: Request body must be a JSON object")

        logger.debug(f"Received screen stocks request: {data}")
        symbols = data.get('symbols', [])

        # Validate the number of symbols
        if not symbols:
            raise HTTPException(status_code=400, detail="No symbols provided")
        if len(symbols) > MAX_SYMBOLS:
            logger.warning(f"Too many symbols requested: {len(symbols)} by client {client_ip}")
            raise HTTPException(status_code=400, detail=f"Too many symbols. Maximum allowed is {MAX_SYMBOLS}")

        # Fetch stock data using MarketData.screen_stocks
        start_time = time.time()
        stock_data = await market_data.screen_stocks(symbols)
        logger.debug(f"screen_stocks took {time.time() - start_time:.2f} seconds")

        if not stock_data:
            logger.error("Failed to fetch stock data from MarketData")
            raise HTTPException(status_code=500, detail="Failed to fetch stock data")

        # Validate the stock data: ensure it's a list of tuples with 8 elements
        validated_stocks = []
        for stock in stock_data:
            if not isinstance(stock, tuple):
                logger.warning(f"Invalid stock entry (not a tuple): {stock}")
                continue
            if len(stock) != 8:  # Updated to expect 8 elements
                logger.warning(f"Invalid stock tuple (wrong length, expected 8): {stock}")
                continue
            if not isinstance(stock[0], str):
                logger.warning(f"Invalid stock tuple (symbol is not a string): {stock}")
                continue
            validated_stocks.append(stock)

        if not validated_stocks:
            logger.warning("No valid stock data after validation.")
            return []

        # Format the response as a list of dictionaries for the frontend
        stock_list = [
            {
                "symbol": stock[0],
                "price": stock[1],
                "change": stock[2],
                "volume": stock[3],
                "change_percentage": stock[4],
                "bid": stock[5],
                "ask": stock[6],
                "market_cap": stock[7]  # Added market cap
            }
            for stock in validated_stocks
        ]

        return stock_list
    except ValueError as ve:
        logger.error(f"Failed to parse JSON request body: {str(ve)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format in request body")
    except Exception as e:
        logger.error(f"Error in screen_stocks: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=Config.FLASK_HOST, port=Config.FLASK_PORT)