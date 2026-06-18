"""Filter panel — 可复用的高级筛选组件"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton
)
from PySide6.QtCore import Qt, Signal


class FilterPanel(QWidget):
    """可复用的筛选面板，发射 filter_changed 信号"""

    filter_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 地区筛选
        layout.addWidget(QLabel("地区:"))
        self.region_combo = QComboBox()
        self.region_combo.addItems(["全部", "同城", "同省"])
        self.region_combo.setFixedWidth(80)
        layout.addWidget(self.region_combo)
        self.region_input = QLineEdit()
        self.region_input.setPlaceholderText("城市名")
        self.region_input.setFixedWidth(100)
        layout.addWidget(self.region_input)

        # 时效筛选
        layout.addWidget(QLabel("时效:"))
        self.time_combo = QComboBox()
        self.time_combo.addItems(["全部", "1天", "3天", "7天", "30天"])
        self.time_combo.setFixedWidth(70)
        layout.addWidget(self.time_combo)

        # 账号类型
        layout.addWidget(QLabel("账号:"))
        self.account_combo = QComboBox()
        self.account_combo.addItems(["全部", "个人", "企业", "蓝V"])
        self.account_combo.setFixedWidth(70)
        layout.addWidget(self.account_combo)

        # 粉丝量
        layout.addWidget(QLabel("粉丝:"))
        self.fans_min = QLineEdit()
        self.fans_min.setPlaceholderText("最小")
        self.fans_min.setFixedWidth(60)
        layout.addWidget(self.fans_min)
        layout.addWidget(QLabel("-"))
        self.fans_max = QLineEdit()
        self.fans_max.setPlaceholderText("最大")
        self.fans_max.setFixedWidth(60)
        layout.addWidget(self.fans_max)

        # 筛选按钮
        apply_btn = QPushButton("🔍 筛选")
        apply_btn.setStyleSheet(
            "QPushButton{background-color:#89b4fa;color:#1e1e2e;border-radius:6px;"
            "padding:6px 14px;font-weight:bold;}"
            "QPushButton:hover{background-color:#b4d0fb;}"
        )
        apply_btn.clicked.connect(self._emit_filter)
        layout.addWidget(apply_btn)

        reset_btn = QPushButton("重置")
        reset_btn.setStyleSheet(
            "QPushButton{border:1px solid #45475a;border-radius:6px;padding:6px 10px;color:#a6adc8;}"
            "QPushButton:hover{background-color:#313244;}"
        )
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)

        layout.addStretch()

    def _emit_filter(self):
        account_map = {"全部": "", "个人": "personal", "企业": "business", "蓝V": "verified"}
        time_map = {"全部": 0, "1天": 1, "3天": 3, "7天": 7, "30天": 30}

        region = ""
        rc = self.region_combo.currentText()
        if rc == "同城":
            region = self.region_input.text().strip()
        elif rc == "同省":
            region = self.region_input.text().strip()

        config = {
            "region": region,
            "time_days": time_map.get(self.time_combo.currentText(), 0),
            "account_type": account_map.get(self.account_combo.currentText(), ""),
            "min_follower_count": int(self.fans_min.text() or 0),
            "max_follower_count": int(self.fans_max.text() or 999999999),
        }
        self.filter_changed.emit(config)

    def _reset(self):
        self.region_combo.setCurrentIndex(0)
        self.region_input.clear()
        self.time_combo.setCurrentIndex(0)
        self.account_combo.setCurrentIndex(0)
        self.fans_min.clear()
        self.fans_max.clear()
        self.filter_changed.emit({})
