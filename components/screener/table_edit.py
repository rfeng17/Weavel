from PySide6.QtWidgets import QMenu, QTableWidget
from PySide6.QtGui import QPainter, QPen, QColor, QAction, QDrag
from PySide6.QtCore import Qt, QMimeData, QByteArray
import logging

logger = logging.getLogger(__name__)

class CustomTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.drop_row = -1  # Track the row where the drop indicator should be drawn
        self.highlight_row = -1  # Track the row to highlight

    def set_drop_row(self, row):
        """Set the row where the drop indicator should be drawn and the row to highlight."""
        self.drop_row = row
        # Highlight the row above the drop position (or the last row if dropping at the end)
        if row >= self.rowCount():
            self.highlight_row = self.rowCount() - 1
        else:
            self.highlight_row = row - 1 if row > 0 else -1
        self.viewport().update()  # Trigger a repaint

    def clear_drop_indicator(self):
        """Clear the drop indicator and highlight."""
        self.drop_row = -1
        self.highlight_row = -1
        self.viewport().update()  # Trigger a repaint

    def paintEvent(self, event):
        """Override paintEvent to draw a custom drop indicator (underline)."""
        super().paintEvent(event)

        if self.drop_row < 0:
            return  # No drop indicator to draw

        painter = QPainter(self.viewport())
        pen = QPen(QColor("#FF5555"), 2, Qt.SolidLine)  # Red underline, 2 pixels thick
        painter.setPen(pen)

        # Calculate the y-position of the underline
        y_pos = 0
        if self.drop_row < self.rowCount():
            # Draw the underline at the top of the target row
            y_pos = self.rowViewportPosition(self.drop_row)
        else:
            # Draw the underline at the bottom of the last row
            last_row = self.rowCount() - 1
            y_pos = self.rowViewportPosition(last_row) + self.rowHeight(last_row)

        # Draw the underline across the width of the table
        painter.drawLine(0, y_pos, self.viewport().width(), y_pos)
        painter.end()

        # Highlight the row above the drop position (or the last row if dropping at the end)
        if self.highlight_row >= 0:
            for col in range(self.columnCount()):
                item = self.item(self.highlight_row, col)
                if item:
                    item.setBackground(QColor("#4C566A"))  # Highlight color (same as hover color)

class TableEdit:
    def __init__(self, table, parent):
        self.table = table  # Should be an instance of CustomTableWidget
        self.parent = parent  # Reference to StockScreener instance

        # Set up context menu for removing stocks
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        # Enable drag-and-drop for reordering rows
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDragDropMode(QTableWidget.DragDrop)
        self.table.setDropIndicatorShown(False)  # Disable default indicator; we'll draw our own
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        # Override drag-and-drop events
        self.table.dragEnterEvent = self.dragEnterEvent
        self.table.dragMoveEvent = self.dragMoveEvent
        self.table.dropEvent = self.dropEvent
        self.table.startDrag = self.startDrag
        self.table.dragLeaveEvent = self.dragLeaveEvent  # Add dragLeaveEvent to clear indicator

    def show_context_menu(self, pos):
        """Show a context menu on right-click with an option to remove the selected stock."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        menu = QMenu(self.table)
        remove_action = QAction("Remove Stock", self.table)
        remove_action.triggered.connect(self.remove_selected_stock)
        menu.addAction(remove_action)
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def remove_selected_stock(self):
        """Remove the selected stock from the screener and update the UI immediately."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        symbol = self.table.item(row, 0).text()

        if symbol in self.parent.symbols:
            self.parent.symbols.remove(symbol)
            self.parent._save_symbols()
            self.parent.filtered_stocks = [stock for stock in self.parent.filtered_stocks if stock[0] != symbol]
            self.parent.update_table()
            self.parent.start_update()

    def startDrag(self, supportedActions):
        """Initiate a drag operation with the source row index."""
        source_row = self.table.currentRow()
        if source_row < 0:
            return

        mime_data = QMimeData()
        data = QByteArray()
        data.append(str(source_row).encode())
        mime_data.setData("application/x-screener-row", data)

        drag = QDrag(self.table)
        drag.setMimeData(mime_data)
        drag.exec_(Qt.MoveAction)

    def dragEnterEvent(self, event):
        """Accept drag events if they contain the custom MIME type."""
        if event.mimeData().hasFormat("application/x-screener-row"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Update the drop indicator position during drag."""
        if event.mimeData().hasFormat("application/x-screener-row"):
            # Determine the target row based on the mouse position
            drop_pos = event.pos()
            target_row = self.table.rowAt(drop_pos.y())
            if target_row < 0:
                # If the mouse is below the last row, set the drop position to the end
                target_row = self.table.rowCount()

            # Update the drop indicator position
            self.table.set_drop_row(target_row)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Clear the drop indicator when the drag leaves the table."""
        self.table.clear_drop_indicator()
        event.accept()

    def dropEvent(self, event):
        """Handle the drop event to reorder rows and update the underlying data."""
        if event.mimeData().hasFormat("application/x-screener-row"):
            data = event.mimeData().data("application/x-screener-row")
            source_row = int(data.data().decode())

            drop_pos = event.pos()
            target_row = self.table.rowAt(drop_pos.y())
            if target_row < 0:
                target_row = self.table.rowCount() - 1

            if source_row == target_row:
                self.table.clear_drop_indicator()
                event.ignore()
                return

            logger.debug(f"Dragging row {source_row} to row {target_row}")

            with self.parent.lock:
                stock = self.parent.filtered_stocks.pop(source_row)
                if target_row >= len(self.parent.filtered_stocks):
                    self.parent.filtered_stocks.append(stock)
                else:
                    self.parent.filtered_stocks.insert(target_row, stock)

                self.parent.sort_column = -1
                self.parent.sort_order = Qt.AscendingOrder

                self.parent.update_table()

                self.table.viewport().update()

            self.table.clear_drop_indicator()
            event.acceptProposedAction()
        else:
            event.ignore()