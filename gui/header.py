from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QLineEdit, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QPropertyAnimation, QSize
from PySide6.QtGui import QIcon

class TitleContainer(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            background-color: #3B4252;
            border-radius: 15px;
            padding: 10px;
        """)
        self.setMinimumWidth(150)
        self.setMaximumWidth(150)  # Start collapsed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(10)

        # Logo
        self.logo_label = QLabel()
        self.logo_label.setPixmap(QIcon("./gui/icons/header/logo.png").pixmap(40, 40))
        self.logo_label.setStyleSheet("background-color: transparent;")
        layout.addWidget(self.logo_label)

        # Title
        self.title_label = QLabel("Weavel")
        self.title_label.setStyleSheet("font-size: 32px; font-weight: bold; background-color: transparent;")
        self.title_opacity = QGraphicsOpacityEffect(self.title_label)
        self.title_opacity.setOpacity(0)  # Start hidden
        self.title_label.setGraphicsEffect(self.title_opacity)
        layout.addWidget(self.title_label)

        # Animations
        self.width_animation = QPropertyAnimation(self, b"maximumWidth")
        self.width_animation.setDuration(300)

        self.opacity_animation = QPropertyAnimation(self.title_opacity, b"opacity")
        self.opacity_animation.setDuration(300)

    def enterEvent(self, event):
        """Expand container and show title on hover."""
        self.width_animation.setStartValue(150)
        self.width_animation.setEndValue(300)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.width_animation.start()
        self.opacity_animation.start()

    def leaveEvent(self, event):
        """Collapse container and hide title when mouse leaves."""
        if not self.underMouse():
            self.width_animation.setStartValue(300)
            self.width_animation.setEndValue(150)
            self.opacity_animation.setStartValue(1.0)
            self.opacity_animation.setEndValue(0.0)
            self.width_animation.start()
            self.opacity_animation.start()

class SearchBar(QWidget):
    """Custom widget for search bar with centered icon."""
    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            background-color: #3B4252;
            border-radius: 15px;
        """)
        self.setFixedHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)  # Margins to center the icon
        layout.setSpacing(5)  # Space between icon and text

        # Search icon
        self.icon_label = QLabel()
        self.icon_label.setPixmap(QIcon("./gui/icons/header/search.png").pixmap(24, 24))  # Smaller icon for better fit
        self.icon_label.setStyleSheet("background-color: transparent;")
        self.icon_label.setAlignment(Qt.AlignCenter)  # Center the icon vertically
        self.icon_label.setFixedWidth(24)  # Ensure icon doesn’t stretch
        layout.addWidget(self.icon_label)

        # Search input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search stocks...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: transparent;  /* No background for the QLineEdit */
                border: none;
                padding: 10px;
                color: white;
                font-size: 18px;
            }
        """)
        layout.addWidget(self.search_input, stretch=1)

    def enterEvent(self, event):
        """Apply hover effect to the entire search bar."""
        self.setStyleSheet("""
            background-color: #4C566A;
            border-radius: 15px;
        """)

    def leaveEvent(self, event):
        """Revert to default style when mouse leaves."""
        if not self.underMouse():
            self.setStyleSheet("""
                background-color: #3B4252;
                border-radius: 15px;
            """)
            
class Header(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(90)
        self.setStyleSheet("background-color: #2E3440; color: white;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(20)

        # Logo and Title container
        self.title_container = TitleContainer()
        layout.addWidget(self.title_container)

        # Search bar
        self.search_bar = SearchBar()
        layout.addWidget(self.search_bar, stretch=1)