from PySide6.QtWidgets import QMenu, QTableWidget
from PySide6.QtGui import QDrag, QPainter, QPen, QColor, QAction
from PySide6.QtCore import Qt, QMimeData, QByteArray, Signal, QObject
import logging

logger = logging.getLogger(__name__)

class CustomTableWidget(QTableWidget):
    row_order_changed = Signal(list)  # Signal to emit when rows are reordered

    def __init__(self, parent=None):
        super().__init__(parent)
        self.drop_row = -1
        self.highlight_row = -1

        # Enable drag-and-drop
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.InternalMove)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setDropIndicatorShown(False)  # We'll use a custom indicator

    def set_drop_row(self, row):
        self.drop_row = row
        if row >= self.rowCount():
            self.highlight_row = self.rowCount() - 1
        else:
            self.highlight_row = row - 1 if row > 0 else -1
        self.viewport().update()

    def clear_drop_indicator(self):
        self.drop_row = -1
        self.highlight_row = -1
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)

        if self.drop_row < 0:
            return

        painter = QPainter(self.viewport())
        pen = QPen(QColor("#FF5555"), 2, Qt.SolidLine)
        painter.setPen(pen)

        y_pos = 0
        if self.drop_row < self.rowCount():
            y_pos = self.rowViewportPosition(self.drop_row)
        else:
            last_row = self.rowCount() - 1
            y_pos = self.rowViewportPosition(last_row) + self.rowHeight(last_row)

        painter.drawLine(0, y_pos, self.viewport().width(), y_pos)
        painter.end()

        if self.highlight_row >= 0:
            for col in range(self.columnCount()):
                item = self.item(self.highlight_row, col)
                if item:
                    item.setBackground(QColor("#4C566A"))

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-screener-row"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-screener-row"):
            drop_pos = event.pos()
            target_row = self.rowAt(drop_pos.y())
            if target_row < 0:
                target_row = self.rowCount()
            self.set_drop_row(target_row)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.clear_drop_indicator()
        event.accept()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-screener-row"):
            source_row = self.currentRow()
            target_row = self.rowAt(event.pos().y())

            # Adjust target_row for dropping at the bottom
            if target_row < 0:
                target_row = self.rowCount()

            if source_row == -1 or source_row == target_row:
                self.clear_drop_indicator()
                event.ignore()
                return

            # If the source row is before the target row, adjust the target row
            # since removing the source row will shift the rows
            if source_row < target_row:
                target_row -= 1

            logger.debug(f"Dragging row {source_row} to row {target_row}")

            # Store the items from the source row
            items = []
            for col in range(self.columnCount()):
                item = self.item(source_row, col)
                items.append(item.clone() if item else None)

            # Remove the source row
            self.removeRow(source_row)

            # Insert a new row at the target position
            self.insertRow(target_row)

            # Populate the new row with the stored items
            for col, item in enumerate(items):
                if item:
                    self.setItem(target_row, col, item)

            # Update the selection
            self.setCurrentCell(target_row, self.currentColumn())

            # Emit the new order of symbols
            new_order = []
            for row in range(self.rowCount()):
                item = self.item(row, 0)  # Symbol is in column 0
                if item:
                    new_order.append(item.text())
            self.row_order_changed.emit(new_order)

            self.clear_drop_indicator()
            event.acceptProposedAction()
        else:
            event.ignore()

    def startDrag(self, supportedActions):
        source_row = self.currentRow()
        if source_row < 0:
            return

        mime_data = QMimeData()
        data = QByteArray()
        data.append(str(source_row).encode())
        mime_data.setData("application/x-screener-row", data)

        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec_(Qt.MoveAction)

class TableEdit(QObject):
    trigger_start_update = Signal()
    table_updated = Signal()

    def __init__(self, table, parent, screener_list):
        super().__init__(parent)
        self.table = table
        self.parent = parent
        self.screener_list = screener_list

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        # Connect the row_order_changed signal
        self.table.row_order_changed.connect(self.on_row_order_changed)

    def show_context_menu(self, pos):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        menu = QMenu(self.table)
        remove_action = QAction("Remove Stock", self.table)
        remove_action.triggered.connect(self.remove_selected_stock)
        menu.addAction(remove_action)
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def remove_selected_stock(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        symbol = self.table.item(row, 0).text()

        with self.parent.lock:
            if symbol in self.screener_list.symbols:
                self.screener_list.symbols.remove(symbol)
                # Also remove from display_order
                if symbol in self.screener_list.display_order:
                    self.screener_list.display_order.remove(symbol)
                self.parent._save_screener_lists()
                self.screener_list.filtered_stocks = [stock for stock in self.screener_list.filtered_stocks if stock[0] != symbol]

        self.table_updated.emit()
        self.trigger_start_update.emit()

    def on_row_order_changed(self, new_order):
        # Update the display_order in screener_list
        with self.parent.lock:
            self.screener_list.display_order = new_order
            self.screener_list.sort_column = -1  # Reset sorting
            self.screener_list.sort_order = Qt.AscendingOrder
            self.parent._save_screener_lists()
        self.table_updated.emit()