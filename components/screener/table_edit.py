from PySide6.QtWidgets import QMenu
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt

class TableEdit:
    def __init__(self, table, parent):
        self.table = table
        self.parent = parent  # Reference to StockScreener instance
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        """Show a context menu on right-click with an option to remove the selected stock."""
        # Get the selected row
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return  # No row selected, do nothing

        # Create the context menu
        menu = QMenu(self.table)
        remove_action = QAction("Remove Stock", self.table)
        remove_action.triggered.connect(self.remove_selected_stock)
        menu.addAction(remove_action)

        # Show the menu at the cursor position
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def remove_selected_stock(self):
        """Remove the selected stock from the screener and update the UI immediately."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # Get the symbol from the selected row (column 0 is the symbol)
        row = selected_rows[0].row()
        symbol = self.table.item(row, 0).text()

        # Remove the symbol from self.symbols
        if symbol in self.parent.symbols:
            self.parent.symbols.remove(symbol)
            self.parent._save_symbols()  # Save the updated symbols list
            # Remove the stock from filtered_stocks locally
            self.parent.filtered_stocks = [stock for stock in self.parent.filtered_stocks if stock[0] != symbol]
            # Update the table immediately
            self.parent.update_table()
            # Trigger a background refresh of the remaining stocks
            self.parent.start_update()