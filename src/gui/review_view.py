"""Review queue page"""
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QMessageBox)

logger = logging.getLogger(__name__)


class ReviewPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QHBoxLayout()
        title = QLabel("审核队列")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()

        self.stats_label = QLabel("待审核: 0")
        self.stats_label.setStyleSheet("color:#f9e2af;font-size:14px;")
        header.addWidget(self.stats_label)

        ab = QPushButton("✅ 批量通过")
        ab.setStyleSheet("QPushButton{background-color:#a6e3a1;color:#1e1e2e;border-radius:6px;padding:8px 16px;font-weight:bold;}")
        ab.clicked.connect(self.approve_selected)
        header.addWidget(ab)

        rb = QPushButton("❌ 批量拒绝")
        rb.setStyleSheet("QPushButton{background-color:#f38ba8;color:#1e1e2e;border-radius:6px;padding:8px 16px;font-weight:bold;}")
        rb.clicked.connect(self.reject_selected)
        header.addWidget(rb)

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["选择", "ID", "类型", "任务ID", "内容", "创建时间", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        try:
            from services.review_service import ReviewService
            svc = ReviewService()
            actions = svc.get_pending_reviews()
            stats = svc.get_review_stats()

            self.stats_label.setText(f"待审核: {stats.get('reviewing', 0)} | 已通过: {stats.get('approved', 0)} | 已拒绝: {stats.get('rejected', 0)}")

            self.table.setRowCount(len(actions))
            for i, a in enumerate(actions):
                # Checkbox
                cb = QTableWidgetItem()
                cb.setCheckState(0)
                self.table.setItem(i, 0, cb)
                self.table.setItem(i, 1, QTableWidgetItem(str(a.id)))
                self.table.setItem(i, 2, QTableWidgetItem(a.action_type))
                self.table.setItem(i, 3, QTableWidgetItem(str(a.task_id)))
                content = (a.content[:50] + "...") if a.content and len(a.content) > 50 else (a.content or "")
                self.table.setItem(i, 4, QTableWidgetItem(content))
                self.table.setItem(i, 5, QTableWidgetItem(a.created_at.strftime("%m-%d %H:%M") if a.created_at else ""))
                self.table.setItem(i, 6, QTableWidgetItem(a.status))
        except Exception as e:
            logger.error(f"Review list refresh failed: {e}")

    def _get_selected_ids(self):
        ids = []
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item and item.checkState() == 2:  # Qt.Checked
                id_item = self.table.item(i, 1)
                if id_item:
                    ids.append(int(id_item.text()))
        return ids

    def approve_selected(self):
        ids = self._get_selected_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先勾选要操作的条目")
            return
        if QMessageBox.question(self, "确认", f"确定通过 {len(ids)} 条?") == QMessageBox.Yes:
            from services.review_service import ReviewService
            count = ReviewService().approve(ids)
            QMessageBox.information(self, "完成", f"已通过 {count} 条")
            self.refresh()

    def reject_selected(self):
        ids = self._get_selected_ids()
        if not ids:
            QMessageBox.information(self, "提示", "请先勾选要操作的条目")
            return
        if QMessageBox.question(self, "确认", f"确定拒绝 {len(ids)} 条?") == QMessageBox.Yes:
            from services.review_service import ReviewService
            count = ReviewService().reject(ids)
            QMessageBox.information(self, "完成", f"已拒绝 {count} 条")
            self.refresh()
