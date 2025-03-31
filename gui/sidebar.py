from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QGraphicsOpacityEffect, QLabel
from PySide6.QtCore import Qt, QPropertyAnimation, QSize, QParallelAnimationGroup
from PySide6.QtGui import QIcon

class SidebarButton(QWidget):
    """Custom widget for sidebar buttons with separate icon and text for text-only opacity."""
    def __init__(self, icon_path, text):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)  # Center the content

        # Icon
        self.icon_label = QLabel()
        self.icon_label.setPixmap(QIcon(icon_path).pixmap(QSize(40, 40)))
        self.icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.icon_label)

        # Text
        self.text_label = QLabel(text)
        self.text_label.setStyleSheet("""
            font-size: 16px; 
            color: white; 
            background-color: transparent;  /* No background for text */
        """)
        self.text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.text_label)

        # Opacity effect for text only
        self.opacity_effect = QGraphicsOpacityEffect(self.text_label)
        self.opacity_effect.setOpacity(0)  # Start hidden (collapsed)
        self.text_label.setGraphicsEffect(self.opacity_effect)
        
class Sidebar(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(80)
        self.setMaximumWidth(80)
        self.setStyleSheet("background-color: #2E3440; color: white;")
        self.is_expanded = False  # Start collapsed
        self.is_animating = False  # Flag to prevent multiple animations
        
        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(15, 15, 15, 15)
        self.layout.setSpacing(20)
        
        # Button style (applied to all buttons for homogeneity)
        self.button_style = """
            background-color: #3B4252; 
            border-radius: 15px;  /* More rounded edges */
            padding: 10px;
        """
        self.button_hover_style = """
            background-color: #4C566A;  /* Hover effect */
            border-radius: 15px;
            padding: 10px;
        """
        
        # Hamburger menu button at the top
        self.menu_btn = QPushButton()
        self.menu_btn.setIcon(QIcon("./gui/icons/sidebar/right-arrow.png"))
        self.menu_btn.setIconSize(QSize(40, 40))
        self.menu_btn.setStyleSheet(self.button_style)
        self.menu_btn.setFixedHeight(80)
        self.menu_btn.setMinimumWidth(60)
        self.menu_btn.setMaximumWidth(60)
        self.menu_btn.clicked.connect(self.toggle_sidebar)
        self.menu_btn.enterEvent = lambda event: self.menu_btn.setStyleSheet(self.button_hover_style)
        self.menu_btn.leaveEvent = lambda event: self.menu_btn.setStyleSheet(self.button_style)
        self.layout.addWidget(self.menu_btn)

        # Stocks button with icon
        self.stocks_btn = SidebarButton("./gui/icons/sidebar/stock.png", "Stocks")  # Stocks icon
        self.stocks_btn.setFixedHeight(120)
        self.stocks_btn.setMinimumWidth(60)
        self.stocks_btn.setMaximumWidth(60)
        self.stocks_btn.setStyleSheet(self.button_style)
        self.stocks_btn.enterEvent = lambda event: self.stocks_btn.setStyleSheet(self.button_hover_style)
        self.stocks_btn.leaveEvent = lambda event: self.stocks_btn.setStyleSheet(self.button_style)
        self.layout.addWidget(self.stocks_btn)

        # Crypto button with icon
        self.crypto_btn = SidebarButton("./gui/icons/sidebar/bitcoin.png", "Crypto")  # Crypto icon
        self.crypto_btn.setFixedHeight(120)
        self.crypto_btn.setMinimumWidth(60)
        self.crypto_btn.setMaximumWidth(60)
        self.crypto_btn.setStyleSheet(self.button_style)
        self.crypto_btn.enterEvent = lambda event: self.crypto_btn.setStyleSheet(self.button_hover_style)
        self.crypto_btn.leaveEvent = lambda event: self.crypto_btn.setStyleSheet(self.button_style)
        self.layout.addWidget(self.crypto_btn)

        # Settings button with icon
        self.settings_btn = SidebarButton("./gui/icons/sidebar/setting.png", "Settings")  # Settings icon
        self.settings_btn.setFixedHeight(120)
        self.settings_btn.setMinimumWidth(60)
        self.settings_btn.setMaximumWidth(60)
        self.settings_btn.setStyleSheet(self.button_style)
        self.settings_btn.enterEvent = lambda event: self.settings_btn.setStyleSheet(self.button_hover_style)
        self.settings_btn.leaveEvent = lambda event: self.settings_btn.setStyleSheet(self.button_style)
        self.layout.addWidget(self.settings_btn)

        self.layout.addStretch()

        # Width animations
        self.sidebar_animation = QPropertyAnimation(self, b"maximumWidth")
        self.sidebar_animation.setDuration(300)

        self.menu_animation = QPropertyAnimation(self.menu_btn, b"maximumWidth")
        self.menu_animation.setDuration(300)

        self.stocks_animation = QPropertyAnimation(self.stocks_btn, b"maximumWidth")
        self.stocks_animation.setDuration(300)

        self.crypto_animation = QPropertyAnimation(self.crypto_btn, b"maximumWidth")
        self.crypto_animation.setDuration(300)

        self.settings_animation = QPropertyAnimation(self.settings_btn, b"maximumWidth")
        self.settings_animation.setDuration(300)
        
        # Group width animations
        self.width_animation_group = QParallelAnimationGroup()
        self.width_animation_group.addAnimation(self.sidebar_animation)
        self.width_animation_group.addAnimation(self.menu_animation)
        self.width_animation_group.addAnimation(self.stocks_animation)
        self.width_animation_group.addAnimation(self.crypto_animation)
        self.width_animation_group.addAnimation(self.settings_animation)
        self.width_animation_group.finished.connect(self.on_animation_finished)
        
        # Opacity animations for text
        self.stocks_opacity_animation = QPropertyAnimation(self.stocks_btn.opacity_effect, b"opacity")
        self.stocks_opacity_animation.setDuration(300)

        self.crypto_opacity_animation = QPropertyAnimation(self.crypto_btn.opacity_effect, b"opacity")
        self.crypto_opacity_animation.setDuration(300)

        self.settings_opacity_animation = QPropertyAnimation(self.settings_btn.opacity_effect, b"opacity")
        self.settings_opacity_animation.setDuration(300)
        
        # Group opacity animations
        self.opacity_animation_group = QParallelAnimationGroup()
        self.opacity_animation_group.addAnimation(self.stocks_opacity_animation)
        self.opacity_animation_group.addAnimation(self.crypto_opacity_animation)
        self.opacity_animation_group.addAnimation(self.settings_opacity_animation)
        
    def toggle_sidebar(self):
        """Toggle the sidebar with synchronized animations."""
        if self.is_animating:
            return  # Prevent multiple animations
        
        self.is_animating = True
        if self.is_expanded:
            # Collapse
            self.sidebar_animation.setStartValue(250)
            self.sidebar_animation.setEndValue(80)
            self.menu_animation.setStartValue(120)
            self.menu_animation.setEndValue(60)
            self.stocks_animation.setStartValue(120)
            self.stocks_animation.setEndValue(60)
            self.crypto_animation.setStartValue(120)
            self.crypto_animation.setEndValue(60)
            self.settings_animation.setStartValue(120)
            self.settings_animation.setEndValue(60)

            self.stocks_opacity_animation.setStartValue(1.0)
            self.stocks_opacity_animation.setEndValue(0.0)
            self.crypto_opacity_animation.setStartValue(1.0)
            self.crypto_opacity_animation.setEndValue(0.0)
            self.settings_opacity_animation.setStartValue(1.0)
            self.settings_opacity_animation.setEndValue(0.0)
            
            self.menu_btn.setIcon(QIcon("./gui/icons/sidebar/right-arrow.png")) # Switch to arrow
            
        else:
            # Expand
            self.sidebar_animation.setStartValue(80)
            self.sidebar_animation.setEndValue(250)
            self.menu_animation.setStartValue(60)
            self.menu_animation.setEndValue(120)
            self.stocks_animation.setStartValue(60)
            self.stocks_animation.setEndValue(120)
            self.crypto_animation.setStartValue(60)
            self.crypto_animation.setEndValue(120)
            self.settings_animation.setStartValue(60)
            self.settings_animation.setEndValue(120)

            self.stocks_opacity_animation.setStartValue(0.0)
            self.stocks_opacity_animation.setEndValue(1.0)
            self.crypto_opacity_animation.setStartValue(0.0)
            self.crypto_opacity_animation.setEndValue(1.0)
            self.settings_opacity_animation.setStartValue(0.0)
            self.settings_opacity_animation.setEndValue(1.0)
            
            self.menu_btn.setIcon(QIcon("./gui/icons/sidebar/menu-bar.png")) # Switch to hamburger
            
        self.is_expanded = not self.is_expanded
        self.width_animation_group.start()
        self.opacity_animation_group.start()
        
    def on_animation_finished(self):
        """Reset the animation flag when animations are done."""
        self.is_animating = False
        
    def enterEvent(self, event):
        """Expand sidebar on hover if collapsed, but only if not animating."""
        if not self.is_expanded and not self.is_animating:
            self.toggle_sidebar()

    def leaveEvent(self, event):
        """Collapse sidebar when mouse leaves if expanded, but only if not animating."""
        if self.is_expanded and not self.underMouse() and not self.is_animating:
            self.toggle_sidebar()