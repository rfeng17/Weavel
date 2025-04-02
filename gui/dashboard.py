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
        self.setStyleSheet("background-color: transparent; color: white; border: none;")

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