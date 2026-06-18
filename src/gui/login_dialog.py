"""Login dialog shown before main window."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt
from services.user_service import UserService


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SuperClaw - 登录")
        self.setFixedSize(400, 320)
        self.user_service = UserService()
        self.logged_in_user = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 30, 40, 30)

        title = QLabel("SuperClaw")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #89b4fa;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("社媒评论线索运营系统")
        subtitle.setStyleSheet("font-size: 13px; color: #a6adc8;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(10)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("用户名")
        self.username_input.setFixedHeight(40)
        self.username_input.returnPressed.connect(self._on_login)
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setFixedHeight(40)
        self.password_input.returnPressed.connect(self._on_login)
        layout.addWidget(self.password_input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #f38ba8; font-size: 12px;")
        self.error_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.error_label)

        self.login_btn = QPushButton("登  录")
        self.login_btn.setFixedHeight(42)
        self.login_btn.setStyleSheet(
            "QPushButton{background-color:#89b4fa;color:#1e1e2e;border:none;border-radius:8px;"
            "font-size:15px;font-weight:bold;}"
            "QPushButton:hover{background-color:#74c7ec;}"
        )
        self.login_btn.clicked.connect(self._on_login)
        layout.addWidget(self.login_btn)

        layout.addStretch()

    def _on_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.error_label.setText("请输入用户名和密码")
            return
        user = self.user_service.authenticate(username, password)
        if user:
            self.logged_in_user = user
            self.accept()
        else:
            self.error_label.setText("用户名或密码错误，或账号已禁用/过期")
            self.password_input.clear()
            self.password_input.setFocus()
