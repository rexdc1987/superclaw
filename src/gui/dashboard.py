"""Dashboard page"""
import logging
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QGridLayout
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class StatCard(QFrame):
    def __init__(self, title, value="0", icon=""):
        super().__init__()
        self.setFixedHeight(120)
        self.setStyleSheet("QFrame{background-color:#313244;border-radius:12px;padding:15px;}")
        layout = QVBoxLayout(self)
        il = QLabel(icon)
        il.setStyleSheet("font-size:28px;")
        layout.addWidget(il)
        self.vl = QLabel(value)
        self.vl.setStyleSheet("font-size:32px;font-weight:bold;color:#89b4fa;")
        layout.addWidget(self.vl)
        tl = QLabel(title)
        tl.setStyleSheet("color:#a6adc8;font-size:12px;")
        layout.addWidget(tl)

    def set_value(self, v):
        self.vl.setText(str(v))


class DashboardPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QHBoxLayout()
        title = QLabel("仪表盘")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        rb = QPushButton("🔄 刷新")
        rb.clicked.connect(self.refresh)
        header.addWidget(rb)
        layout.addLayout(header)
        layout.addSpacing(20)

        cards = QGridLayout()
        cards.setSpacing(15)
        self.c_acc = StatCard("账号总数", "0", "👤")
        self.c_task = StatCard("活跃任务", "0", "📋")
        self.c_lead = StatCard("线索总数", "0", "🎯")
        self.c_act = StatCard("今日动作", "0", "⚡")
        cards.addWidget(self.c_acc, 0, 0)
        cards.addWidget(self.c_task, 0, 1)
        cards.addWidget(self.c_lead, 0, 2)
        cards.addWidget(self.c_act, 0, 3)
        layout.addLayout(cards)
        layout.addStretch()
        self.refresh()

    def refresh(self):
        try:
            from services.account_service import AccountService
            from services.task_service import TaskService
            from services.lead_service import LeadService
            self.c_acc.set_value(AccountService().get_health_report().get("total", 0))
            self.c_task.set_value(TaskService().get_statistics().get("by_status", {}).get("running", 0))
            self.c_lead.set_value(LeadService().get_lead_statistics().get("total", 0))
        except Exception as e:
            logger.error(f"Dashboard refresh failed: {e}")
