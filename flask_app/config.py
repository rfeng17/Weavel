# config.py
from dotenv import load_dotenv
import os

# Load variables from .env
load_dotenv()

class Config:
    TRADIER_API_TOKEN = os.getenv("TRADIER_API")
    TRADIER_BASE_URL = "https://api.tradier.com/v1"
    
    FLASK_SERVER_ADDRESS = "http://localhost:5000"