from PySide6.QtWidgets import (
    QWidget, 
    QVBoxLayout, 
    QHBoxLayout, 
    QLabel, 
    QStyledItemDelegate, 
    QPushButton, 
    QTableWidgetItem, 
    QHeaderView, 
    QProgressBar, 
    QInputDialog, 
    QMessageBox, 
    QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QRect
from PySide6.QtGui import QIcon, QPen, QColor

import json
import os
import logging
import requests
import threading
import time
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from flask_app.config import Config
from components.screener.table_edit import TableEdit, CustomTableWidget

logger = logging.getLogger(__name__)

class UpDownDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.max_combined_volume = 1

    def set_max_combined_volume(self, max_volume):
        self.max_combined_volume = max(1, max_volume)

    def paint(self, painter, option, index):
        up_volume = index.data(Qt.UserRole) or 0
        down_volume = index.data(Qt.UserRole + 1) or 0

        painter.fillRect(option.rect, QColor("#2E3440"))

        rect = option.rect.adjusted(5, 5, -5, -5)
        total_width = rect.width()
        center_x = rect.center().x()
        height = rect.height()

        max_length = total_width / 2
        up_length = (up_volume / self.max_combined_volume) * max_length
        down_length = (down_volume / self.max_combined_volume) * max_length

        painter.setPen(QPen(Qt.black, 1))
        painter.drawLine(center_x, rect.top(), center_x, rect.bottom())

        if up_volume > 0:
            painter.setPen(QPen(Qt.NoPen))
            painter.setBrush(QColor(Qt.green))
            up_rect = QRect(
                center_x, rect.top(),
                int(up_length), height
            )
            painter.drawRect(up_rect)

        if down_volume > 0:
            painter.setPen(QPen(Qt.NoPen))
            painter.setBrush(QColor(Qt.red))
            down_rect = QRect(
                center_x - int(down_length), rect.top(),
                int(down_length), height
            )
            painter.drawRect(down_rect)

    def sizeHint(self, option, index):
        return option.rect.size()

class ScreenerList:
    def __init__(self, name, symbols=None, display_order=None):
        self.name = name
        self.symbols = symbols if symbols is not None else []
        self.display_order = display_order if display_order is not None else []  # New attribute for display order
        self.filtered_stocks = []
        self.sort_column = -1
        self.sort_order = Qt.AscendingOrder
        self.table = None
        self.table_edit = None
        self.loading_bar = None
        self.container_layout = None
        self.updater = None

class StockUpdater(QThread):
    update_data = Signal(ScreenerList, list)
    set_loading_signal = Signal(ScreenerList, bool)

    def __init__(self, parent, screener_list):
        super().__init__(parent)
        self.parent = parent
        self.screener_list = screener_list
        self.running = True
        # Set up a session with retries
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def run(self):
        while self.running:
            if not self.screener_list.symbols:
                time.sleep(1)
                continue

            try:
                self.set_loading_signal.emit(self.screener_list, True)
                response = self.session.post(
                    "http://127.0.0.1:5000/api/update_quotes",
                    json={"symbols": self.screener_list.symbols, "force_refresh": False},
                    timeout=30  # Increased timeout to 30 seconds
                )
                response.raise_for_status()
                updated_data = response.json()

                new_filtered_stocks = []
                with self.parent.lock:
                    for symbol in self.screener_list.symbols:
                        if symbol in updated_data:
                            data = updated_data[symbol]
                            new_filtered_stocks.append((
                                symbol,
                                data["price"],
                                data["change_percentage"],
                                data.get("market_cap", 0),
                                data["volume"],
                                data["volume_bought"],
                                data["volume_sold"]
                            ))
                    self.screener_list.filtered_stocks = new_filtered_stocks.copy()

                self.update_data.emit(self.screener_list, new_filtered_stocks)
            except requests.exceptions.RequestException as e:
                logger.error(f"Error in StockUpdater for list {self.screener_list.name}: {str(e)}")
                logger.debug(f"Symbols: {self.screener_list.symbols}")
            finally:
                self.set_loading_signal.emit(self.screener_list, False)
                time.sleep(15)

class StockAdder(QThread):
    add_stock_finished = Signal(ScreenerList, tuple)
    set_loading_signal = Signal(ScreenerList, bool)

    def __init__(self, parent, screener_list, symbol):
        super().__init__(parent)
        self.parent = parent
        self.screener_list = screener_list
        self.symbol = symbol
        # Set up a session with retries
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def run(self):
        try:
            self.set_loading_signal.emit(self.screener_list, True)
            response = self.session.post(
                "http://127.0.0.1:5000/api/screen",
                json={"symbols": [self.symbol]},
                timeout=30  # Increased timeout to 30 seconds
            )
            response.raise_for_status()
            stock_data = response.json()

            if stock_data and isinstance(stock_data, list) and len(stock_data) > 0:
                stock = stock_data[0]
                stock_tuple = (
                    stock["symbol"],          # Symbol
                    stock["price"],           # Price
                    stock["change_percentage"],  # Change percentage
                    stock["change"],          # Change
                    stock["volume"],          # Volume
                    stock["bid"],             # Bid
                    stock["ask"]              # Ask
                )
                self.add_stock_finished.emit(self.screener_list, stock_tuple)
            else:
                logger.warning(f"No data returned for symbol: {self.symbol}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error adding stock {self.symbol} to list {self.screener_list.name}: {str(e)}")
        except KeyError as e:
            logger.error(f"Unexpected response format from /api/screen for symbol {self.symbol}: {stock_data}")
            logger.error(f"KeyError: {str(e)}")
        finally:
            self.set_loading_signal.emit(self.screener_list, False)
            
class StartUpdateWorker(QThread):
    update_finished = Signal(ScreenerList, list)
    set_loading_signal = Signal(ScreenerList, bool)

    def __init__(self, parent, screener_list, symbols):
        super().__init__(parent)
        self.parent = parent
        self.screener_list = screener_list
        self.symbols = symbols
        # Set up a session with retries
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retries))

    def run(self):
        try:
            self.set_loading_signal.emit(self.screener_list, True)
            response = self.session.post(
                "http://127.0.0.1:5000/api/screen",
                json={"symbols": self.symbols},
                timeout=30  # Increased timeout to 30 seconds
            )
            response.raise_for_status()
            stock_data = response.json()
            filtered_stocks = [
                (
                    stock["symbol"],          # Symbol
                    stock["price"],           # Price
                    stock["change_percentage"],  # Change percentage
                    stock["change"],          # Change
                    stock["volume"],          # Volume
                    stock["bid"],             # Bid
                    stock["ask"]              # Ask
                )
                for stock in stock_data
            ]
            self.update_finished.emit(self.screener_list, filtered_stocks)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error in StartUpdateWorker for list {self.screener_list.name}: {str(e)}")
            logger.debug(f"Symbols: {self.symbols}")
        except KeyError as e:
            logger.error(f"Unexpected response format from /api/screen: {stock_data}")
            logger.error(f"KeyError: {str(e)}")
        finally:
            self.set_loading_signal.emit(self.screener_list, False)

class StockScreener(QWidget):
    def __init__(self):
        super().__init__()
        self.screener_lists = []
        self.lock = threading.Lock()
        self.update_timers = {}
        self.pending_updates = {}
        self.setup_ui()
        self._load_screener_lists()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        header_label = QLabel("Stock Screener")
        header_label.setStyleSheet("font-size: 24px; color: #ECEFF4; font-weight: bold;")
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_widget = QWidget()
        self.tables_container = QVBoxLayout(scroll_widget)
        self.tables_container.setAlignment(Qt.AlignTop)
        self.tables_container.setSpacing(15)

        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        add_list_button = QPushButton("Add New List")
        add_list_button.clicked.connect(self.create_new_list)
        layout.addWidget(add_list_button)

    def format_market_cap(self, market_cap_billions):
        """
        Format market cap (in billions) to abbreviated form (T, B, M).
        Args:
            market_cap_billions: Market capitalization in billions.
        Returns:
            Formatted string (e.g., '3.11T', '500B', '500M').
        """
        if market_cap_billions >= 1000:
            return f"{market_cap_billions / 1000:.2f}T"  # Trillions
        elif market_cap_billions >= 1:
            return f"{market_cap_billions:.2f}B"  # Billions
        else:
            return f"{market_cap_billions * 1000:.0f}M"  # Millions

    def create_table_for_list(self, screener_list):
        list_container = QVBoxLayout()

        header_layout = QHBoxLayout()
        list_label = QLabel(screener_list.name)
        list_label.setStyleSheet("font-size: 18px; color: #ECEFF4; font-weight: bold;")
        header_layout.addWidget(list_label)

        rename_button = QPushButton()
        rename_button.setIcon(QIcon("./gui/icons/tools/edit.png"))
        rename_button.clicked.connect(
            lambda: self.rename_list(screener_list)
        )
        header_layout.addWidget(rename_button)

        delete_button = QPushButton()
        delete_button.setIcon(QIcon("./gui/icons/tools/delete.png"))
        delete_button.clicked.connect(
            lambda: self.delete_list(screener_list)
        )
        header_layout.addWidget(delete_button)

        header_layout.addStretch()
        list_container.addLayout(header_layout)

        table = CustomTableWidget()
        table.setColumnCount(6)  # Added one column for Volume
        table.setHorizontalHeaderLabels([
            "Symbol", 
            "Price ($)", 
            "Change (%)", 
            "Market Cap",  # Updated header
            "Volume (Shares)", 
            "Up/Down"
        ])
        table.horizontalHeader().setVisible(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeaderItem(0).setToolTip("Stock ticker symbol (e.g., AAPL)")
        table.horizontalHeaderItem(1).setToolTip("Current stock price in USD")
        table.horizontalHeaderItem(2).setToolTip("Daily price change percentage")
        table.horizontalHeaderItem(3).setToolTip("Market capitalization (T: trillions, B: billions, M: millions)")
        table.horizontalHeaderItem(4).setToolTip("Total trading volume (number of shares)")
        table.horizontalHeaderItem(5).setToolTip("Up (green, right) and Down (red, left) volume meter")
        for i in range(table.columnCount()):
            table.horizontalHeaderItem(i).setTextAlignment(Qt.AlignCenter)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(CustomTableWidget.NoEditTriggers)
        table.setStyleSheet("""
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
            QHeaderView::section {
                background-color: #4C566A;
                color: #ECEFF4;
                padding: 4px;
                border: 1px solid #3B4252;
            }
        """)
        table.setSortingEnabled(False)

        header_height = table.horizontalHeader().height()
        table.setRowCount(1)
        row_height = table.rowHeight(0)
        table.setRowCount(0)
        min_height = header_height + (5 * row_height)
        table.setMinimumHeight(min_height)

        up_down_delegate = UpDownDelegate(table)
        table.setItemDelegateForColumn(5, up_down_delegate)  # Updated column index

        table.horizontalHeader().sectionClicked.connect(
            lambda logical_index, sl=screener_list: self.sort_table(sl, logical_index)
        )
        list_container.addWidget(table)

        table_edit = TableEdit(table, self, screener_list)
        table_edit.trigger_start_update.connect(
            lambda: self.handle_start_update(screener_list)
        )
        table_edit.table_updated.connect(
            lambda: self.schedule_table_update(screener_list)
        )

        button_container = QHBoxLayout()
        button_container.addStretch()
        add_stock_button = QPushButton("+")
        add_stock_button.setObjectName(f"AddStockButton_{screener_list.name}")
        add_stock_button.setToolTip("Add a new stock to this list")
        add_stock_button.clicked.connect(
            lambda: self.add_stock(screener_list)
        )
        button_container.addWidget(add_stock_button)
        list_container.addLayout(button_container)

        loading_bar = QProgressBar()
        loading_bar.setRange(0, 0)
        loading_bar.setVisible(False)
        loading_bar.setMaximumHeight(5)
        list_container.addWidget(loading_bar)

        screener_list.table = table
        screener_list.table_edit = table_edit
        screener_list.loading_bar = loading_bar
        screener_list.container_layout = list_container

        self.tables_container.addLayout(list_container)

        update_timer = QTimer(self)
        update_timer.setSingleShot(True)
        update_timer.timeout.connect(
            lambda sl=screener_list: self.deferred_update_table(sl)
        )
        self.update_timers[screener_list] = update_timer
        self.pending_updates[screener_list] = False

        updater = StockUpdater(self, screener_list)
        updater.update_data.connect(self.on_update_data)
        updater.set_loading_signal.connect(self.set_loading)
        updater.start()
        screener_list.updater = updater

    def _load_screener_lists(self):
        try:
            if os.path.exists("json/screener_lists.json"):
                with open("json/screener_lists.json", "r") as f:
                    data = json.load(f)
                    self.screener_lists = []
                    for list_data in data:
                        # Load both symbols and display_order from JSON
                        symbols = list_data.get("symbols", [])
                        display_order = list_data.get("display_order", symbols)  # Fallback to symbols if not present
                        # Ensure display_order contains only valid symbols
                        display_order = [symbol for symbol in display_order if symbol in symbols]
                        # Add any missing symbols to the end of display_order
                        for symbol in symbols:
                            if symbol not in display_order:
                                display_order.append(symbol)
                        screener_list = ScreenerList(
                            name=list_data["name"],
                            symbols=symbols,
                            display_order=display_order
                        )
                        self.screener_lists.append(screener_list)
            if not self.screener_lists:
                self.screener_lists.append(ScreenerList("Default List", ["AAPL", "MSFT", "GOOGL"]))
            for screener_list in self.screener_lists:
                self.create_table_for_list(screener_list)
                self.handle_start_update(screener_list)
        except Exception as e:
            logger.error(f"Error loading screener lists: {e}")
            self.screener_lists = [ScreenerList("Default List", ["AAPL", "MSFT", "GOOGL"])]
            for screener_list in self.screener_lists:
                self.create_table_for_list(screener_list)

    def _save_screener_lists(self):
        try:
            data = [
                {
                    "name": screener_list.name,
                    "symbols": screener_list.symbols,
                    "display_order": screener_list.display_order  # Save the display order
                }
                for screener_list in self.screener_lists
            ]
            with open("json/screener_lists.json", "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving screener lists: {e}")

    def create_new_list(self):
        name, ok = QInputDialog.getText(self, "New Screener List", "Enter list name:")
        if ok and name:
            if any(screener_list.name == name for screener_list in self.screener_lists):
                QMessageBox.warning(self, "Error", "A list with this name already exists.")
                return
            screener_list = ScreenerList(name)
            self.screener_lists.append(screener_list)
            self.create_table_for_list(screener_list)
            self._save_screener_lists()
            self.handle_start_update(screener_list)

    def rename_list(self, screener_list):
        name, ok = QInputDialog.getText(self, "Rename Screener List", "Enter new name:", text=screener_list.name)
        if ok and name:
            if any(sl.name == name for sl in self.screener_lists if sl != screener_list):
                QMessageBox.warning(self, "Error", "A list with this name already exists.")
                return
            screener_list.name = name
            header_layout = screener_list.container_layout.itemAt(0).layout()
            label = header_layout.itemAt(0).widget()
            label.setText(name)
            button_container = screener_list.container_layout.itemAt(2).layout()
            add_stock_button = button_container.itemAt(1).widget()
            add_stock_button.setObjectName(f"AddStockButton_{name}")
            self._save_screener_lists()

    def delete_list(self, screener_list):
        if len(self.screener_lists) <= 1:
            QMessageBox.warning(self, "Error", "Cannot delete the last screener list.")
            return

        reply = QMessageBox.question(
            self,
            "Delete Screener List",
            f"Are you sure you want to delete '{screener_list.name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            screener_list.updater.running = False
            screener_list.updater.wait()

            container_layout = screener_list.container_layout
            while container_layout.count():
                item = container_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    sub_layout = item.layout()
                    while sub_layout.count():
                        sub_item = sub_layout.takeAt(0)
                        if sub_item.widget():
                            sub_item.widget().deleteLater()
                    sub_layout.deleteLater()
            container_layout.deleteLater()

            self.screener_lists.remove(screener_list)
            if screener_list in self.update_timers:
                self.update_timers[screener_list].stop()
                del self.update_timers[screener_list]
            if screener_list in self.pending_updates:
                del self.pending_updates[screener_list]

            self._save_screener_lists()

    def add_stock(self, screener_list):
        symbol, ok = QInputDialog.getText(self, "Add Stock", "Enter stock symbol (e.g., AAPL):")
        if ok and symbol:
            symbol = symbol.upper().strip()
            if symbol in screener_list.symbols:
                QMessageBox.warning(self, "Error", f"Stock {symbol} is already in the list.")
                return
            adder = StockAdder(self, screener_list, symbol)
            adder.add_stock_finished.connect(self.on_add_stock_finished)
            adder.set_loading_signal.connect(self.set_loading)
            adder.start()

    @Slot(ScreenerList, tuple)
    def on_add_stock_finished(self, screener_list, stock_tuple):
        with self.lock:
            if stock_tuple[0] not in screener_list.symbols:
                screener_list.symbols.append(stock_tuple[0])
                # Add the new symbol to the display_order (at the end)
                screener_list.display_order.append(stock_tuple[0])
                screener_list.filtered_stocks.append(stock_tuple)
                self._save_screener_lists()
        self.schedule_table_update(screener_list)

    @Slot(ScreenerList, bool)
    def set_loading(self, screener_list, loading):
        screener_list.loading_bar.setVisible(loading)

    @Slot(ScreenerList, list)
    def on_update_data(self, screener_list, filtered_stocks):
        with self.lock:
            screener_list.filtered_stocks = filtered_stocks
        self.schedule_table_update(screener_list)

    def handle_start_update(self, screener_list):
        if not screener_list.symbols:
            return
        worker = StartUpdateWorker(self, screener_list, screener_list.symbols)
        worker.update_finished.connect(self.on_start_update_finished)
        worker.set_loading_signal.connect(self.set_loading)
        worker.start()

    @Slot(ScreenerList, list)
    def on_start_update_finished(self, screener_list, filtered_stocks):
        with self.lock:
            screener_list.filtered_stocks = filtered_stocks
            # Update display_order based on the initial filtered_stocks order if not set
            if not screener_list.display_order:
                screener_list.display_order = [stock[0] for stock in filtered_stocks]
        self.schedule_table_update(screener_list)

    def schedule_table_update(self, screener_list):
        if screener_list not in self.pending_updates:
            logger.warning(f"ScreenerList {screener_list.name} not found in pending_updates. Skipping update.")
            return
        if not self.pending_updates[screener_list]:
            self.pending_updates[screener_list] = True
            self.update_timers[screener_list].start(50)

    @Slot()
    def deferred_update_table(self, screener_list):
        if screener_list not in self.pending_updates:
            logger.warning(f"ScreenerList {screener_list.name} not found in pending_updates during deferred update. Skipping.")
            return
        self.pending_updates[screener_list] = False
        self.update_table(screener_list)

    def update_table(self, screener_list):
        table = screener_list.table
        with self.lock:
            # Create a mapping of symbol to stock data
            stock_dict = {stock[0]: stock for stock in screener_list.filtered_stocks}
            # Order stocks according to display_order, falling back to available data
            stocks_to_display = []
            # First, add stocks in the display_order that still exist in filtered_stocks
            for symbol in screener_list.display_order:
                if symbol in stock_dict:
                    stocks_to_display.append(stock_dict[symbol])
                    del stock_dict[symbol]  # Remove to avoid duplicates
            # Then, append any remaining stocks that weren't in display_order
            stocks_to_display.extend(stock_dict.values())

            # Apply sorting if a sort column is active
            if screener_list.sort_column >= 0:
                if screener_list.sort_column == 5:  # Up/Down column
                    stocks_to_display.sort(
                        key=lambda x: x[5] - x[6],
                        reverse=(screener_list.sort_order == Qt.DescendingOrder)
                    )
                else:
                    stocks_to_display.sort(
                        key=lambda x: (
                            x[screener_list.sort_column] if screener_list.sort_column != 2 else x[2]
                        ),
                        reverse=(screener_list.sort_order == Qt.DescendingOrder)
                    )
                # Update display_order to reflect the new sorted order
                screener_list.display_order = [stock[0] for stock in stocks_to_display]
                self._save_screener_lists()

        max_combined_volume = 1
        for stock in stocks_to_display:
            up_volume = stock[5]
            down_volume = stock[6]
            combined = up_volume + down_volume
            max_combined_volume = max(max_combined_volume, combined)

        delegate = table.itemDelegateForColumn(5)  # Updated column index
        if delegate:
            delegate.set_max_combined_volume(max_combined_volume)

        current_row_count = table.rowCount()
        new_row_count = len(stocks_to_display)

        if current_row_count != new_row_count:
            table.setRowCount(new_row_count)

        for row, stock in enumerate(stocks_to_display):
            for col in range(5):  # Updated to 5 to include Volume column
                item = table.item(row, col)
                value = stock[col]
                if col == 3:  # Market Cap column
                    new_text = self.format_market_cap(value)  # Format market cap
                elif col == 4:  # Volume column
                    new_text = f"{int(value):,}"  # Format volume with commas
                else:
                    new_text = f"{value:.2f}%" if col == 2 else str(value)
                if not item or item.text() != new_text:
                    item = QTableWidgetItem(new_text)
                    if col == 2:
                        if value > 0:
                            item.setForeground(Qt.green)
                        elif value < 0:
                            item.setForeground(Qt.red)
                    item.setTextAlignment(Qt.AlignCenter)
                    table.setItem(row, col, item)

            # Up/Down column (now column 5)
            up_volume = stock[5]
            down_volume = stock[6]
            item = table.item(row, 5)  # Updated column index
            if not item:
                item = QTableWidgetItem()
                table.setItem(row, 5, item)
            item.setData(Qt.UserRole, up_volume)
            item.setData(Qt.UserRole + 1, down_volume)
            item.setText("")

    def sort_table(self, screener_list, logical_index):
        with self.lock:
            if screener_list.sort_column == logical_index:
                screener_list.sort_order = (
                    Qt.DescendingOrder
                    if screener_list.sort_order == Qt.AscendingOrder
                    else Qt.AscendingOrder
                )
            else:
                screener_list.sort_column = logical_index
                screener_list.sort_order = Qt.AscendingOrder
        self.schedule_table_update(screener_list)

    def closeEvent(self, event):
        for screener_list in self.screener_lists:
            if screener_list.updater:
                screener_list.updater.running = False
                screener_list.updater.wait()
        self._save_screener_lists()  # Ensure the latest order is saved on close
        event.accept()