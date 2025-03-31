from PySide6.QtWidgets import QMainWindow, QVBoxLayout, QHBoxLayout, QWidget
from gui.header import Header
from gui.sidebar import Sidebar
from gui.dashboard import Dashboard
from PySide6.QtCore import Qt

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Weavel Trading")
        self.setGeometry(100, 100, 1920, 1080)  # Adjusted for mobile-like aspect ratio

        # Set the window background to black
        self.setStyleSheet("background-color: #000000;")

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Add header
        self.header = Header()
        layout.addWidget(self.header)

        # Container for sidebar and dashboard
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        # Add sidebar
        self.sidebar = Sidebar()
        container_layout.addWidget(self.sidebar)

        # Add dashboard
        self.dashboard = Dashboard()
        container_layout.addWidget(self.dashboard, stretch=1)

        layout.addWidget(container, stretch=1)