from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTabWidget
from PySide6.QtCore import Qt
from components.screener.screener import StockScreener
import requests
import logging
from flask_app.config import Config

logger = logging.getLogger(__name__)

class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.server_address = Config.FLASK_SERVER_ADDRESS
        self.setStyleSheet("background-color: #2E3440; color: white; border: none;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        # Tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #2E3440;
                margin-top: 15px;
            }
            QTabBar::tab {
                background-color: #3B4252;
                color: white;
                padding: 12px;
                border-radius: 15px;
                font-size: 18px;
                margin-right: 10px;
            }
            QTabBar::tab:selected {
                background-color: #4C566A;
                border-bottom: 2px solid #81A1C1;
            }
            QTabBar::tab:hover:!selected {
                background-color: #4C566A;
            }
        """)
        layout.addWidget(tabs)

        # Stock Screener Tab
        screener_tab = StockScreener()
        tabs.addTab(screener_tab, "Stock Screener")

        # Default Stocks/Indices Tab
        stocks_tab = QWidget()
        stocks_tab.setStyleSheet("background-color: #3B4252; border-radius: 15px; padding: 10px;")
        stocks_layout = QVBoxLayout(stocks_tab)
        stocks_layout.setContentsMargins(10, 10, 10, 10)
        self.spy_label = QLabel("SPY Data: Loading...")
        self.spy_label.setStyleSheet("font-size: 24px; background-color: transparent;")
        stocks_layout.addWidget(self.spy_label)
        tabs.addTab(stocks_tab, "Stocks/Indices")

        # Fetch SPY data
        self.load_spy_data()

    def load_spy_data(self):
        """Load SPY market data from the Flask backend."""
        try:
            response = requests.get(f"{self.server_address}/api/spy")
            response.raise_for_status()
            spy_data = response.json()
            if spy_data:
                self.spy_label.setText(f"SPY Data: {spy_data['candles'][0]['close']}")
            else:
                self.spy_label.setText("SPY Data: Failed to load")
        except Exception as e:
            logger.warning(f"Failed to load SPY data: {str(e)}")
            self.spy_label.setText(f"SPY Data: Failed to load - {str(e)}")