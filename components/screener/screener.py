from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QInputDialog, QMessageBox
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QObject
from PySide6.QtGui import QColor
import logging
import requests
import threading
from flask_app.config import Config
from components.screener.table_edit import TableEdit
import json
import os

logger = logging.getLogger(__name__)

class StockUpdater(QObject):
    """Class to handle asynchronous stock updates and emit signals for UI updates."""
    update_ui_signal = Signal()

    def __init__(self, server_address, parent=None):
        super().__init__(parent)
        self.server_address = server_address
        self.filtered_stocks = []
        self.lock = threading.Lock()

    def start_update(self, filtered_stocks):
        if not filtered_stocks:
            logger.debug("No stocks to update price and volume for.")
            return

        with self.lock:
            self.filtered_stocks = filtered_stocks.copy()

        thread = threading.Thread(target=self.update_price_and_volume)
        thread.daemon = True
        thread.start()

    def update_price_and_volume(self):
        try:
            with self.lock:
                symbols = [stock[0] for stock in self.filtered_stocks]
            logger.debug(f"Fetching updated quotes for symbols: {symbols}")

            response = requests.post(
                f"{self.server_address}/api/update_quotes",
                json={"symbols": symbols},
                timeout=5
            )
            response.raise_for_status()
            quote_data = response.json()
            logger.debug(f"Backend Response: {quote_data}")

            if "error" in quote_data:
                logger.error(f"Error from backend: {quote_data['error']}")
                return

            has_changes = False
            with self.lock:
                for i, stock in enumerate(self.filtered_stocks):
                    symbol = stock[0]
                    if symbol in quote_data:
                        new_price = quote_data[symbol]["price"]
                        new_volume = quote_data[symbol]["volume"]
                        new_change = quote_data[symbol]["change_percentage"]
                        if (stock[1] != new_price or
                            stock[3] != new_volume or
                            stock[4] != new_change):
                            has_changes = True
                            self.filtered_stocks[i] = (
                                symbol,
                                new_price,
                                stock[2],
                                new_volume,
                                new_change
                            )
                            if i == 0:
                                logger.debug(f"Updated {symbol}: Price={new_price}, "
                                             f"Volume={new_volume}, Change={new_change}")

            if has_changes:
                self.update_ui_signal.emit()

        except requests.exceptions.Timeout:
            logger.error("Request to backend timed out while fetching updated quotes.")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error fetching quotes from backend: {str(http_err)}")
            logger.error(f"Response Text: {http_err.response.text if http_err.response else 'No response'}")
        except Exception as e:
            logger.error(f"Error updating price and volume: {str(e)}")
        finally:
            self.update_ui_signal.emit()

    def get_filtered_stocks(self):
        with self.lock:
            return self.filtered_stocks.copy()

class StockAdder(QObject):
    """Class to handle asynchronous stock addition and emit signals for UI updates."""
    add_stock_signal = Signal(list)  # Emits the filtered stocks
    error_signal = Signal(str)  # Emits an error message if the operation fails

    def __init__(self, server_address, parent=None):
        super().__init__(parent)
        self.server_address = server_address
        self.lock = threading.Lock()

    def add_stock(self, new_symbol, all_symbols, filters):
        """Add a new stock and fetch its data in a separate thread."""
        self.new_symbol = new_symbol  # Store the new symbol for use in _fetch_and_filter_stocks
        self.all_symbols = all_symbols  # Store all symbols for validation
        self.filters = filters
        thread = threading.Thread(target=self._fetch_and_filter_stocks)
        thread.daemon = True
        thread.start()

    def _fetch_and_filter_stocks(self):
        """Fetch data for the new stock from the backend."""
        try:
            # Request data for only the new stock
            request_data = {
                "symbols": [self.new_symbol],
                "min_price": self.filters["min_price"],
                "max_price": self.filters["max_price"],
                "min_volume": self.filters["min_volume"],
                "market_cap_filter": self.filters["market_cap_filter"]
            }
            logger.debug(f"Sending request to backend for new stock {self.new_symbol}: {request_data}")
            response = requests.post(
                f"{self.server_address}/api/screen",
                json=request_data
            )
            response.raise_for_status()
            stocks = response.json()
            logger.debug(f"Received response from backend for {self.new_symbol}: {stocks}")

            # Process the response
            if not stocks:
                self.error_signal.emit(f"Ticker not found: {self.new_symbol}")
                return

            stock = stocks[0]  # Expecting data for only one stock
            symbol = stock[0]
            change_percentage = stock[4]
            if change_percentage is None:
                logger.warning(f"Stock {symbol}: change percentage is None")
                self.error_signal.emit(f"Ticker not found: {self.new_symbol}")
                return

            if not (self.filters["min_change"] <= change_percentage <= self.filters["max_change"]):
                self.error_signal.emit(f"Stock {self.new_symbol} does not meet filter criteria")
                return

            # Emit the new stock data
            self.add_stock_signal.emit(stock)

        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP Error fetching stock data for {self.new_symbol}: {str(http_err)}")
            self.error_signal.emit(f"HTTP Error: {str(http_err)}")
        except Exception as e:
            logger.error(f"Error adding stock {self.new_symbol}: {str(e)}")
            self.error_signal.emit(str(e))

class StockScreener(QWidget):
    def __init__(self):
        super().__init__()
        self.server_address = Config.FLASK_SERVER_ADDRESS
        
        self.stocks_file = "json/stocks.json"
        default_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "JPM", "BAC", "WMT", "KO"]
        if os.path.exists(self.stocks_file):
            try:
                with open(self.stocks_file, 'r') as f:
                    data = json.load(f)
                    self.symbols = data.get("symbols", default_symbols)
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Error reading stocks.json: {str(e)}. Using default symbols.")
                self.symbols = default_symbols
                self._save_symbols()  # Save the default symbols to the file
        else:
            logger.info("stocks.json not found. Creating with default symbols.")
            self.symbols = default_symbols
            self._save_symbols()  # Create the file with default symbols
        self.filtered_stocks = []
        self.sort_column = -1
        self.sort_order = Qt.AscendingOrder
        
        self.setStyleSheet("""
            QWidget {
                background-color: #3B4252;
                border-radius: 15px;
                padding: 15px;
            }
            QLabel {
                color: #D8DEE9;
                font-size: 16px;
                font-weight: bold;
            }
            QLineEdit {
                background-color: #2E3440;
                color: #D8DEE9;
                border: 1px solid #4C566A;
                border-radius: 8px;
                padding: 8px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #81A1C1;
            }
            QComboBox {
                background-color: #2E3440;
                color: #D8DEE9;
                border: 1px solid #4C566A;
                border-radius: 8px;
                padding: 8px;
                font-size: 14px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: url(down_arrow.png);
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #2E3440;
                color: #D8DEE9;
                selection-background-color: #4C566A;
                border: 1px solid #4C566A;
                border-radius: 8px;
            }
            QPushButton {
                background-color: #5E81AC;
                color: #ECEFF4;
                padding: 10px;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #81A1C1;
            }
            QPushButton:pressed {
                background-color: #4C566A;
            }
            QPushButton#AddStockButton {
                background-color: #5E81AC;
                color: #ECEFF4;
                padding: 5px;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                min-width: 30px;
                min-height: 30px;
            }
            QPushButton#AddStockButton:hover {
                background-color: #81A1C1;
            }
            QPushButton#AddStockButton:pressed {
                background-color: #4C566A;
            }
            QTableWidget {
                background-color: #2E3440;
                color: #D8DEE9;
                border: 1px solid #4C566A;
                border-radius: 10px;
                font-size: 14px;
            }
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #4C566A;
                color: #ECEFF4;
            }
            QTableWidget QHeaderView::section {
                background-color: #4C566A;
                color: #ECEFF4;
                padding: 8px;
                border: 1px solid #5E81AC;
                font-size: 14px;
                font-weight: bold;
                height: 48px;
            }
            QTableWidget QHeaderView::section:hover {
                background-color: #5E81AC;
            }
            QTableWidget QHeaderView::section:vertical {
                background-color: transparent;
                color: transparent;
            }
            QTableWidget QTableCornerButton::section {
                background-color: #2E3440;
                border: 1px solid #4C566A;
            }
            QProgressBar {
                background-color: #2E3440;
                border: 1px solid #4C566A;
                border-radius: 2px;
                text-align: center;
                color: #D8DEE9;
                font-size: 10px;
                height: 5px;
            }
            QProgressBar::chunk {
                background-color: #81A1C1;
                border-radius: 1px;
            }
        """)
        self.setup_ui()
        self.screen_stocks()
        self.stock_updater = StockUpdater(self.server_address, parent=self)
        self.stock_adder = StockAdder(self.server_address, parent=self)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.start_update)
        self.update_timer.start(15000)
        self.stock_updater.update_ui_signal.connect(self.handle_update)
        self.stock_adder.add_stock_signal.connect(self.handle_add_stock)
        self.stock_adder.error_signal.connect(self.handle_add_stock_error)
        # Set up the context menu for the table
        self.table_edit = TableEdit(self.results_table, self)

    def setup_ui(self):
        """Set up the UI components for the stock screener."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        header_LabeL = QLabel("Stock Screener")
        header_LabeL.setStyleSheet("font-size: 24px; color: #ECEFF4; font-weight: bold;")
        header_LabeL.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_LabeL)

        # Filter Section
        filter_container = QWidget()
        filter_container.setStyleSheet("background-color: #434C5E; border-radius: 10px; padding: 10px;")
        filter_layout = QHBoxLayout(filter_container)
        filter_layout.setSpacing(15)

        # Price Range Filter
        price_layout = QVBoxLayout()
        price_label = QLabel("Price Range ($)")
        price_label.setToolTip("Filter stocks by price range (e.g., $100 to $200)")
        price_layout.addWidget(price_label)
        price_input_layout = QHBoxLayout()
        self.min_price = QLineEdit()
        self.min_price.setPlaceholderText("Min Price")
        self.min_price.setToolTip("Enter the minimum price (e.g., 100)")
        price_input_layout.addWidget(self.min_price)
        self.max_price = QLineEdit()
        self.max_price.setPlaceholderText("Max Price")
        self.max_price.setToolTip("Enter the maximum price (e.g., 200), or leave blank for no limit")
        price_input_layout.addWidget(self.max_price)
        price_layout.addLayout(price_input_layout)
        filter_layout.addLayout(price_layout)

        # Price Change Filter
        change_layout = QVBoxLayout()
        change_label = QLabel("Price Change (%)")
        change_label.setToolTip("Filter stocks by daily price change percentage (e.g., -5 to 5)")
        change_layout.addWidget(change_label)
        change_input_layout = QHBoxLayout()
        self.min_change = QLineEdit()
        self.min_change.setPlaceholderText("Min Change")
        self.min_change.setToolTip("Enter the minimum price change percentage (e.g., -5)")
        change_input_layout.addWidget(self.min_change)
        self.max_change = QLineEdit()
        self.max_change.setPlaceholderText("Max Change")
        self.max_change.setToolTip("Enter the maximum price change percentage (e.g., 5), or leave blank for no limit")
        change_input_layout.addWidget(self.max_change)
        change_layout.addLayout(change_input_layout)
        filter_layout.addLayout(change_layout)

        # Market Cap Filter
        market_cap_layout = QVBoxLayout()
        market_cap_label = QLabel("Market Cap")
        market_cap_label.setToolTip("Filter stocks by market capitalization")
        market_cap_layout.addWidget(market_cap_label)
        self.market_cap_filter = QComboBox()
        self.market_cap_filter.addItems(["Any", "< $2B", "$2B - $10B", "> $10B"])
        self.market_cap_filter.setToolTip("Select a market cap range")
        market_cap_layout.addWidget(self.market_cap_filter)
        filter_layout.addLayout(market_cap_layout)

        # Volume Filter
        volume_layout = QVBoxLayout()
        volume_label = QLabel("Min Volume")
        volume_label.setToolTip("Filter stocks by minimum trading volume")
        volume_layout.addWidget(volume_label)
        self.min_volume = QLineEdit()
        self.min_volume.setPlaceholderText("e.g., 1000000")
        self.min_volume.setToolTip("Enter the minimum trading volume (e.g., 1000000)")
        volume_layout.addWidget(self.min_volume)
        filter_layout.addLayout(volume_layout)

        layout.addWidget(filter_container)

        # Button Layout
        button_layout = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.screen_stocks)
        button_layout.addWidget(self.apply_button)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_filters)
        button_layout.addWidget(self.reset_button)
        layout.addLayout(button_layout)

        # Table and Add Stock Button Layout
        table_container = QVBoxLayout()

        # Results Table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels([
            "Symbol", 
            "Price ($)", 
            "Change (%)", 
            "Market Cap ($B)", 
            "Volume (Shares)"
        ])
        logger.debug(f"Header labels set: {self.results_table.horizontalHeaderItem(0).text()}, "
                     f"{self.results_table.horizontalHeaderItem(1).text()}, "
                     f"{self.results_table.horizontalHeaderItem(2).text()}, "
                     f"{self.results_table.horizontalHeaderItem(3).text()}, "
                     f"{self.results_table.horizontalHeaderItem(4).text()}")
        self.results_table.horizontalHeader().setVisible(True)
        logger.debug(f"Header visibility: {self.results_table.horizontalHeader().isVisible()}")
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeaderItem(0).setToolTip("Stock ticker symbol (e.g., AAPL)")
        self.results_table.horizontalHeaderItem(1).setToolTip("Current stock price in USD")
        self.results_table.horizontalHeaderItem(2).setToolTip("Daily price change percentage")
        self.results_table.horizontalHeaderItem(3).setToolTip("Market capitalization in billions of USD")
        self.results_table.horizontalHeaderItem(4).setToolTip("Trading volume in number of shares")
        for i in range(self.results_table.columnCount()):
            self.results_table.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.horizontalHeader().resizeSections(QHeaderView.Stretch)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setStyleSheet("""
            QTableWidget {
                background-color: #2E3440;
                alternate-background-color: #3B4252;
            }
            QTableWidget::item {
                text-align: center;
            }
            QTableWidget::item:hover {
                background-color: #4C566A;
            }
        """)
        self.results_table.setSortingEnabled(False)
        self.results_table.horizontalHeader().sectionClicked.connect(self.sort_table)
        self.results_table.viewport().update()
        table_container.addWidget(self.results_table)
        
        # Right click menu
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SingleSelection)

        # Add Stock Button (below the table, aligned to the right)
        button_container = QHBoxLayout()
        button_container.addStretch()
        self.add_stock_button = QPushButton("+")
        self.add_stock_button.setObjectName("AddStockButton")
        self.add_stock_button.setToolTip("Add a new stock to the screener")
        self.add_stock_button.clicked.connect(self.add_stock)
        button_container.addWidget(self.add_stock_button)
        table_container.addLayout(button_container)

        layout.addLayout(table_container)

        # Loading Indicator
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setVisible(False)
        self.loading_bar.setMaximumHeight(5)
        layout.addWidget(self.loading_bar)
        
    def _save_symbols(self):
        """Save the current symbols list to stocks.json."""
        try:
            with open(self.stocks_file, 'w') as f:
                json.dump({"symbols": self.symbols}, f, indent=4)
            logger.debug(f"Saved symbols to {self.stocks_file}: {self.symbols}")
        except Exception as e:
            logger.error(f"Error saving to {self.stocks_file}: {str(e)}")

    def add_stock(self):
        """Prompt the user to add a new stock symbol to the screener."""
        symbol, ok = QInputDialog.getText(
            self,
            "Add Stock",
            "Enter stock symbol (e.g., AAPL):",
            QLineEdit.Normal
        )
        if ok and symbol:
            symbol = symbol.strip().upper()
            if not symbol.isalnum():
                logger.error(f"Invalid stock symbol: {symbol}. Must be alphanumeric.")
                QMessageBox.warning(self, "Error", "Invalid stock symbol. It must be alphanumeric (e.g., AAPL).")
                return
            if symbol in self.symbols:
                logger.debug(f"Stock symbol {symbol} already in screener.")
                QMessageBox.information(self, "Info", f"Stock symbol {symbol} is already in the screener.")
                return

            # Add the symbol with placeholder data and update the UI immediately
            self.symbols.append(symbol)
            self._save_symbols()  # Save the updated symbols list
            placeholder_stock = (symbol, "N/A", 0, 0, 0)  # Placeholder: symbol, price, market cap, volume, change
            self.filtered_stocks.append(placeholder_stock)
            self.update_table()
            logger.debug(f"Temporarily added stock symbol with placeholder: {symbol}. New symbols list: {self.symbols}")

            # Fetch the actual data for the new stock asynchronously
            self.loading_bar.setVisible(True)
            self.add_stock_button.setEnabled(False)
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.stock_adder.add_stock(symbol, self.symbols, self.validate_filters())

            # Speed up the timer to update in 1 second
            remaining_time = self.update_timer.remainingTime()
            if remaining_time > 1000:  # If more than 1 second remains
                self.update_timer.stop()
                self.update_timer.start(1000)  # Schedule the next update in 1 second

    @Slot(tuple)
    def handle_add_stock(self, new_stock):
        """Handle the signal from StockAdder when stock addition is successful."""
        # Replace the placeholder entry with the actual data
        for i, stock in enumerate(self.filtered_stocks):
            if stock[0] == new_stock[0]:  # Match by symbol
                self.filtered_stocks[i] = new_stock
                break
        # Update the table only if StockUpdater isn't about to run
        if not self.update_timer.isActive():
            self.update_table()
        logger.debug(f"Successfully updated stock {new_stock[0]}. New filtered stocks: {self.filtered_stocks}")
        self.loading_bar.setVisible(False)
        self.add_stock_button.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        
    @Slot(str)
    def handle_add_stock_error(self, error_message):
        """Handle the error signal from StockAdder when stock addition fails."""
        # Remove the last added symbol and its placeholder since it failed
        if self.symbols:
            failed_symbol = self.symbols[-1]
            self.symbols.pop()
            self._save_symbols()  # Save the updated symbols list
            self.filtered_stocks = [stock for stock in self.filtered_stocks if stock[0] != failed_symbol]
            self.update_table()
            logger.debug(f"Removed failed stock symbol: {failed_symbol}. New symbols list: {self.symbols}")
        QMessageBox.critical(self, "Error", f"Failed to add stock: {error_message}")
        self.loading_bar.setVisible(False)
        self.add_stock_button.setEnabled(True)
        self.apply_button.setEnabled(True)
        self.reset_button.setEnabled(True)
        # Speed up the timer to update in 1 second
        remaining_time = self.update_timer.remainingTime()
        if remaining_time > 1000:  # If more than 1 second remains
            self.update_timer.stop()
            self.update_timer.start(1000)  # Schedule the next update in 1 second

    def validate_filters(self):
        """Validate all filter inputs and return the parsed values."""
        filters = {
            "min_price": 0,
            "max_price": 1e9,
            "min_change": -1e9,
            "max_change": 1e9,
            "min_volume": 0,
            "market_cap_filter": "Any"
        }

        if self.min_price.text():
            if not self.is_valid_float(self.min_price.text()):
                raise ValueError("Minimum price must be a valid number")
            filters["min_price"] = float(self.min_price.text())
        if self.max_price.text():
            if not self.is_valid_float(self.max_price.text()):
                raise ValueError("Maximum price must be a valid number")
            filters["max_price"] = float(self.max_price.text())

        if self.min_change.text():
            if not self.is_valid_float(self.min_change.text()):
                raise ValueError("Minimum price change must be a valid number")
            filters["min_change"] = float(self.min_change.text())
        if self.max_change.text():
            if not self.is_valid_float(self.max_change.text()):
                raise ValueError("Maximum price change must be a valid number")
            filters["max_change"] = float(self.max_change.text())

        if self.min_volume.text():
            if not self.is_valid_int(self.min_volume.text()):
                raise ValueError("Minimum volume must be a valid integer")
            filters["min_volume"] = int(self.min_volume.text())

        filters["market_cap_filter"] = self.market_cap_filter.currentText()

        return filters

    def reset_filters(self):
        """Reset all filters to their default values and refresh the table."""
        self.min_price.clear()
        self.max_price.clear()
        self.min_change.clear()
        self.max_change.clear()
        self.min_volume.clear()
        self.market_cap_filter.setCurrentText("Any")
        self.sort_column = -1
        self.sort_order = Qt.AscendingOrder
        self.screen_stocks()

    def screen_stocks(self):
        """Fetch and display filtered stock data from the Flask backend."""
        try:
            filters = self.validate_filters()

            self.loading_bar.setVisible(True)
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.add_stock_button.setEnabled(False)
            self.results_table.setRowCount(0)

            request_data = {
                "symbols": self.symbols,
                "min_price": filters["min_price"],
                "max_price": filters["max_price"],
                "min_volume": filters["min_volume"],
                "market_cap_filter": filters["market_cap_filter"]
            }
            logger.debug(f"Sending request to backend: {request_data}")
            response = requests.post(
                f"{self.server_address}/api/screen",
                json=request_data
            )
            response.raise_for_status()
            stocks = response.json()
            logger.debug(f"Received response from backend: {stocks}")

            invalid_symbols = []
            filtered_stocks = []
            for stock in stocks:
                symbol = stock[0]
                change_percentage = stock[4]
                if change_percentage is None:
                    logger.warning(f"Stock {symbol}: change percentage is None")
                    invalid_symbols.append(symbol)
                    continue
                if filters["min_change"] <= change_percentage <= filters["max_change"]:
                    filtered_stocks.append(stock)
            self.filtered_stocks = filtered_stocks

            if invalid_symbols:
                raise ValueError(f"Ticker(s) not found: {', '.join(invalid_symbols)}")

            self.update_table()

        except ValueError as ve:
            logger.error(f"Input validation error: {str(ve)}")
            QMessageBox.critical(self, "Error", str(ve))
        except Exception as e:
            logger.error(f"Error screening stocks: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error screening stocks: {str(e)}")
        finally:
            self.loading_bar.setVisible(False)
            self.apply_button.setEnabled(True)
            self.reset_button.setEnabled(True)
            self.add_stock_button.setEnabled(True)

    @Slot()
    def update_table(self):
        """Update the table with the current filtered stocks, applying sorting if needed."""
        if self.sort_column >= 0:
            self.filtered_stocks.sort(
                key=lambda x: (
                    x[self.sort_column] if self.sort_column != 2 else x[4]
                ),
                reverse=(self.sort_order == Qt.DescendingOrder)
            )

        self.results_table.setRowCount(len(self.filtered_stocks))
        for row, stock in enumerate(self.filtered_stocks):
            symbol, price, market_cap, volume, change_percentage = stock
            if row == 0:
                logger.debug(f"Processing stock: {symbol}, Price: {price}, Market Cap: {market_cap}, Volume: {volume}, Change: {change_percentage}")
            
            self.results_table.setItem(row, 0, QTableWidgetItem(str(symbol)))
            # Handle price: display as-is if it's a string, otherwise format as float
            price_display = price if isinstance(price, str) else f"{price:.2f}"
            price_item = QTableWidgetItem(price_display)
            # Color-code price based on change_percentage
            if not isinstance(change_percentage, str) and change_percentage is not None:
                price_item.setForeground(QColor("green" if change_percentage >= 0 else "red"))
            self.results_table.setItem(row, 1, price_item)
            # Handle change percentage: display as-is if it's a string, otherwise format as float and color-code
            change_display = change_percentage if isinstance(change_percentage, str) else f"{change_percentage:+.2f}"
            change_item = QTableWidgetItem(change_display)
            if not isinstance(change_percentage, str) and change_percentage is not None:
                change_item.setForeground(QColor("green" if change_percentage >= 0 else "red"))
            self.results_table.setItem(row, 2, change_item)
            # Handle market cap: display as-is if it's a string, otherwise format
            market_cap_display = market_cap if isinstance(market_cap, str) else f"{market_cap/1e3:.1f}"
            self.results_table.setItem(row, 3, QTableWidgetItem(market_cap_display))
            # Handle volume: display as-is if it's a string, otherwise format with commas
            volume_display = volume if isinstance(volume, str) else f"{int(volume):,}"
            self.results_table.setItem(row, 4, QTableWidgetItem(volume_display))

        self.results_table.resizeColumnsToContents()
        self.results_table.horizontalHeader().setVisible(True)
        self.results_table.horizontalHeader().resizeSections(QHeaderView.Stretch)
        self.results_table.viewport().update()
        self.loading_bar.setVisible(False)

    def sort_table(self, column):
        """Sort the table by the clicked column."""
        if self.sort_column == column:
            self.sort_order = Qt.DescendingOrder if self.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self.sort_column = column
            self.sort_order = Qt.AscendingOrder
        self.update_table()

    def start_update(self, show_loading_bar=True):
        """Trigger the update process in StockUpdater."""
        if show_loading_bar:
            self.loading_bar.setVisible(True)
        self.stock_updater.start_update(self.filtered_stocks)

    @Slot()
    def handle_update(self, hide_loading_bar=True):
        """Handle the update signal from StockUpdater by updating filtered_stocks and the UI."""
        self.filtered_stocks = self.stock_updater.get_filtered_stocks()
        self.update_table()
        if hide_loading_bar:
            self.loading_bar.setVisible(False)
        # Revert the timer to its regular 15-second interval if it was sped up
        if self.update_timer.interval() != 15000:
            self.update_timer.stop()
            self.update_timer.start(15000)  # Revert to 15-second interval

    def is_valid_float(self, value):
        """Validate if a string can be converted to a float."""
        try:
            float(value)
            return True
        except ValueError:
            return False

    def is_valid_int(self, value):
        """Validate if a string can be converted to an integer."""
        try:
            int(value)
            return True
        except ValueError:
            return False

    def __del__(self):
        """Stop the timer when the widget is destroyed."""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()