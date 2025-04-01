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