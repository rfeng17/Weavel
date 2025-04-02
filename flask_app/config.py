# config.py
from dotenv import load_dotenv
import os

# Load variables from .env
load_dotenv()

class Config:
    FLASK_HOST = "0.0.0.0"
    FLASK_PORT = 5000
    FLASK_DEBUG = True
    FLASK_SERVER_ADDRESS = "http://localhost:5000"
    
    TRADIER_API_TOKEN = os.getenv("TRADIER_API")
    TRADIER_BASE_URL = "https://api.tradier.com/v1"
    
    # Alpaca Markets
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    ALPACA_BASE_URL = "https://data.alpaca.markets"
    
    #POLYGON_API = os.getenv("POLYGON_API")
    
    MARKET_OPEN_HOUR = 9    # 9:30 AM Eastern
    MARKET_OPEN_MINUTE = 30
    MARKET_CLOSE_HOUR = 16  # 4:00 PM Eastern
    MARKET_CLOSE_MINUTE = 0
    TIMEZONE = "US/Eastern"