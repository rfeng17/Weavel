from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QTableWidget, QTableWidgetItem
from PySide6.QtCore import Qt
import logging
import requests

logger = logging.getLogger(__name__)

class StockScreener(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            background-color: #3B4252;
            border-radius: 15px;
            padding: 10px;
        """)
        self.setup_ui()

    def setup_ui(self):
        """Set up the UI components for the stock screener."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Filter Section
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)

        # Price Range
        price_layout = QHBoxLayout()
        price_layout.addWidget(QLabel("Price Range:"))
        self.min_price = QLineEdit()
        self.min_price.setPlaceholderText("Min")
        self.min_price.setStyleSheet("background-color: #2E3440; color: white; border-radius: 5px; padding: 5px;")
        self.max_price = QLineEdit()
        self.max_price.setPlaceholderText("Max")
        self.max_price.setStyleSheet("background-color: #2E3440; color: white; border-radius: 5px; padding: 5px;")
        price_layout.addWidget(self.min_price)
        price_layout.addWidget(self.max_price)
        filter_layout.addLayout(price_layout)

        # Market Cap Filter
        market_cap_layout = QHBoxLayout()
        market_cap_layout.addWidget(QLabel("Market Cap:"))
        self.market_cap_filter = QComboBox()
        self.market_cap_filter.addItems(["Any", "< $2B", "$2B - $10B", "> $10B"])
        self.market_cap_filter.setStyleSheet("background-color: #2E3440; color: white; border-radius: 5px; padding: 5px;")
        market_cap_layout.addWidget(self.market_cap_filter)
        filter_layout.addLayout(market_cap_layout)

        # Volume Filter
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Min Volume:"))
        self.min_volume = QLineEdit()
        self.min_volume.setPlaceholderText("e.g., 1000000")
        self.min_volume.setStyleSheet("background-color: #2E3440; color: white; border-radius: 5px; padding: 5px;")
        volume_layout.addWidget(self.min_volume)
        filter_layout.addLayout(volume_layout)

        layout.addLayout(filter_layout)

        # Screen Button
        self.screen_button = QPushButton("Screen Stocks")
        self.screen_button.setStyleSheet("""
            QPushButton {
                background-color: #3B4252;
                color: white;
                padding: 10px;
                border-radius: 15px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #4C566A;
            }
        """)
        self.screen_button.clicked.connect(self.screen_stocks)
        layout.addWidget(self.screen_button)

        # Results Table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(4)
        self.results_table.setHorizontalHeaderLabels(["Symbol", "Price", "Market Cap", "Volume"])
        self.results_table.setStyleSheet("""
            QTableWidget {
                background-color: #2E3440;
                color: white;
                border-radius: 15px;
                padding: 5px;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #3B4252;
                color: white;
                padding: 5px;
                border-radius: 5px;
            }
        """)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.results_table)

    def screen_stocks(self):
        """Fetch and display filtered stock data from the Flask backend."""
        try:
            # Sample list of symbols
            symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "JPM", "BAC", "WMT", "KO"]

            # Get filter values
            min_price = float(self.min_price.text()) if self.min_price.text() else 0
            max_price = float(self.max_price.text()) if self.max_price.text() else float('inf')
            min_volume = int(self.min_volume.text()) if self.min_volume.text() else 0
            market_cap_filter = self.market_cap_filter.currentText()

            # Call the Flask backend
            response = requests.post(
                "http://localhost:5000/api/screen",
                json={
                    "symbols": symbols,
                    "min_price": min_price,
                    "max_price": max_price,
                    "min_volume": min_volume,
                    "market_cap_filter": market_cap_filter
                }
            )
            response.raise_for_status()
            filtered_stocks = response.json()

            # Update table
            self.results_table.setRowCount(len(filtered_stocks))
            for row, (symbol, price, market_cap, volume) in enumerate(filtered_stocks):
                self.results_table.setItem(row, 0, QTableWidgetItem(symbol))
                self.results_table.setItem(row, 1, QTableWidgetItem(f"{price:.2f}"))
                self.results_table.setItem(row, 2, QTableWidgetItem(f"${market_cap/1e9:.1f}B"))
                self.results_table.setItem(row, 3, QTableWidgetItem(f"{volume:,}"))
            self.results_table.resizeColumnsToContents()

        except Exception as e:
            logger.error(f"Error screening stocks: {str(e)}")
            self.results_table.setRowCount(1)
            self.results_table.setItem(0, 0, QTableWidgetItem(f"Error: {str(e)}"))