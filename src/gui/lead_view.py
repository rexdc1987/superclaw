"""Lead management page with advanced filter panel"""
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QSpinBox, QMessageBox)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class LeadPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        header = QHBoxLayout()
        title = QLabel("线索管理")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        self.sf = QComboBox()
        self.sf.addItem("全部状态", "")
        self.sf.addItems(["new", "contacted", "replied", "converted", "lost"])
        self.sf.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.sf)
        self.ms = QSpinBox()
        self.ms.setRange(0, 100)
        self.ms.setPrefix("最低分: ")
        self.ms.valueChanged.connect(self.refresh)
        header.addWidget(self.ms)
        eb = QPushButton("📥 导出CSV")
        eb.clicked.connect(self.export)
        header.addWidget(eb)
        layout.addLayout(header)

        # Advanced filter panel
        from gui.filter_panel import FilterPanel
        self.filter_panel = FilterPanel()
        self.filter_panel.filter_changed.connect(self._on_filter_changed)
        layout.addWidget(self.filter_panel)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["ID", "平台", "用户昵称", "地区", "粉丝数", "评分", "状态", "触达次数"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.stats = QLabel("共 0 条线索")
        self.stats.setStyleSheet("color:#a6adc8;")
        layout.addWidget(self.stats)

        self._active_filter = {}
        self.refresh()

    def _on_filter_changed(self, config):
        self._active_filter = config
        self.refresh()

    def refresh(self):
        try:
            from services.lead_service import LeadService
            status = self.sf.currentData() or None
            ms = self.ms.value() or None

            # If advanced filter is active, use FilterService
            if self._active_filter:
                from services.filter_service import FilterService
                task_id = self._active_filter.pop("task_id", None)
                if task_id:
                    leads = FilterService().apply_filters(task_id, self._active_filter)
                    self._populate_table(leads, len(leads))
                    return

            r = LeadService().get_leads(status=status, min_score=ms)
            items = r.get("items", [])
            self._populate_table(items, r.get("total", 0))
        except Exception as e:
            logger.error(f"Lead list refresh failed: {e}")

    def _populate_table(self, items, total):
        self.table.setRowCount(len(items))
        for i, l in enumerate(items):
            self.table.setItem(i, 0, QTableWidgetItem(str(l.id)))
            self.table.setItem(i, 1, QTableWidgetItem(l.platform))
            self.table.setItem(i, 2, QTableWidgetItem(l.user_nickname))
            region = getattr(l, "user_region", "") or ""
            self.table.setItem(i, 3, QTableWidgetItem(region))
            fans = getattr(l, "follower_count", 0) or 0
            self.table.setItem(i, 4, QTableWidgetItem(str(fans) if fans else "-"))
            self.table.setItem(i, 5, QTableWidgetItem(str(l.score)))
            self.table.setItem(i, 6, QTableWidgetItem(l.status))
            self.table.setItem(i, 7, QTableWidgetItem(str(l.contact_count)))
        self.stats.setText(f"共 {total} 条线索")

    def export(self):
        try:
            from services.export_service import ExportService
            path = ExportService().export_leads_csv()
            QMessageBox.information(self, "导出成功", f"已导出到: {path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
