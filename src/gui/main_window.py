"""Main Window with sidebar navigation"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QStackedWidget, QLabel, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, Signal


class MainWindow(QMainWindow):
    logout_signal = Signal()

    def __init__(self, current_user=None):
        super().__init__()
        self.current_user = current_user
        self.setWindowTitle("SuperClaw 社媒评论线索运营系统")
        self.setMinimumSize(1280, 800)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet("background-color: #181825; border-right: 1px solid #313244;")
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(10, 20, 10, 20)

        logo = QLabel("SuperClaw")
        logo.setStyleSheet("font-size: 20px; font-weight: bold; color: #89b4fa; padding: 10px;")
        logo.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(logo)
        sb_layout.addSpacing(5)

        # Current user info
        if current_user:
            user_label = QLabel(f"\U0001f464 {current_user.nickname or current_user.username}")
            user_label.setStyleSheet("color: #cdd6f4; font-size: 13px; font-weight: bold; padding: 4px 10px;")
            user_label.setAlignment(Qt.AlignCenter)
            sb_layout.addWidget(user_label)

            if current_user.phone:
                phone_label = QLabel(f"\U0001f4f1 {current_user.phone}")
                phone_label.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 1px 10px;")
                phone_label.setAlignment(Qt.AlignCenter)
                sb_layout.addWidget(phone_label)

            if current_user.position:
                pos_label = QLabel(f"\U0001f4bc {current_user.position}")
                pos_label.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 1px 10px;")
                pos_label.setAlignment(Qt.AlignCenter)
                sb_layout.addWidget(pos_label)

            if current_user.days_remaining() >= 0:
                days = current_user.days_remaining()
                days_label = QLabel(f"剩余 {days} 天")
                days_color = "#f38ba8" if days <= 7 else "#a6e3a1"
                days_label.setStyleSheet(f"color: {days_color}; font-size: 11px; padding: 2px 10px;")
                days_label.setAlignment(Qt.AlignCenter)
                sb_layout.addWidget(days_label)

        sb_layout.addSpacing(10)

        self.nav_buttons = []
        pages = [
            ("\U0001f4ca 仪表盘", 0),
            ("\U0001f464 账号管理", 1),
            ("\U0001f4cb 任务中心", 2),
            ("\U0001f3af 线索管理", 3),
            ("\U0001f4dd 话术模板", 4),
            ("\U0001f4dc 运行日志", 5),
            ("\U0001f50d 审核队列", 6),
            ("\U0001f3af 打法模板", 7),
            ("\U0001f6e1\ufe0f 风控中心", 8),
        ]
        if current_user and current_user.role == "admin":
            pages.append(("\U0001f465 用户管理", 9))

        for text, idx in pages:
            btn = QPushButton(text)
            btn.setFixedHeight(40)
            btn.setStyleSheet(
                "QPushButton{background:transparent;border:none;text-align:left;"
                "padding-left:15px;border-radius:8px;font-size:14px;}"
                "QPushButton:hover{background-color:#313244;}"
            )
            btn.clicked.connect(lambda checked, i=idx: self._switch(i))
            sb_layout.addWidget(btn)
            self.nav_buttons.append(btn)
        sb_layout.addStretch()

        # Logout / Switch account buttons
        switch_btn = QPushButton("\U0001f504 切换账号")
        switch_btn.setFixedHeight(32)
        switch_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #45475a;border-radius:6px;"
            "padding:4px;font-size:12px;color:#a6adc8;}"
            "QPushButton:hover{background-color:#313244;color:#cdd6f4;}"
        )
        switch_btn.clicked.connect(self._on_switch_account)
        sb_layout.addWidget(switch_btn)

        logout_btn = QPushButton("\U0001f6aa 退出登录")
        logout_btn.setFixedHeight(32)
        logout_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #f38ba8;border-radius:6px;"
            "padding:4px;font-size:12px;color:#f38ba8;}"
            "QPushButton:hover{background-color:#45475a;}"
        )
        logout_btn.clicked.connect(self._on_logout)
        sb_layout.addWidget(logout_btn)

        ver = QLabel("v0.2.0")
        ver.setStyleSheet("color:#585b70;font-size:11px;")
        ver.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(ver)
        layout.addWidget(sidebar)

        # Pages
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        from gui.dashboard import DashboardPage
        from gui.account_view import AccountPage
        from gui.task_view import TaskPage
        from gui.lead_view import LeadPage
        from gui.template_view import TemplatePage
        from gui.log_view import LogPage
        from gui.review_view import ReviewPage
        from gui.risk_view import RiskPage
        from gui.playbook_view import PlaybookPage

        self.stack.addWidget(DashboardPage())
        self.stack.addWidget(AccountPage())
        self.stack.addWidget(TaskPage())
        self.stack.addWidget(LeadPage())
        self.stack.addWidget(TemplatePage())
        self.stack.addWidget(LogPage())
        self.stack.addWidget(ReviewPage())
        self.stack.addWidget(PlaybookPage())
        self.stack.addWidget(RiskPage())

        if current_user and current_user.role == "admin":
            from gui.user_view import UserPage
            self.stack.addWidget(UserPage())

    def _switch(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_buttons):
            if i == idx:
                btn.setStyleSheet(
                    "QPushButton{background-color:#313244;border:none;text-align:left;"
                    "padding-left:15px;border-radius:8px;font-size:14px;color:#89b4fa;}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton{background:transparent;border:none;text-align:left;"
                    "padding-left:15px;border-radius:8px;font-size:14px;}"
                    "QPushButton:hover{background-color:#313244;}"
                )

    def _on_switch_account(self):
        reply = QMessageBox.question(
            self, "切换账号",
            "确定要切换到其他账号吗？当前操作将被保存。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.logout_signal.emit()
            self.close()

    def _on_logout(self):
        reply = QMessageBox.question(
            self, "退出登录",
            "确定要退出登录吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.logout_signal.emit()
            self.close()
