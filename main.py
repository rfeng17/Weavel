import sys
from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow

def main():
    # Initialize Schwab authentication

    # Start the GUI application
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()