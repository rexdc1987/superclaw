"""Account management page"""
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog, QFormLayout,
    QLineEdit, QDialogButtonBox, QMessageBox)

logger = logging.getLogger(__name__)


class AccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加账号")
        self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self.pf = QComboBox()
        self.pf.addItems(["douyin", "xiaohongshu", "kuaishou", "bilibili"])
        layout.addRow("平台:", self.pf)
        self.un = QLineEdit()
        layout.addRow("用户名:", self.un)
        self.dn = QLineEdit()
        layout.addRow("显示名称:", self.dn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_data(self):
        return {"platform": self.pf.currentText(), "username": self.un.text().strip(), "display_name": self.dn.text().strip()}


class AccountPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        header = QHBoxLayout()
        title = QLabel("账号管理")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        self.pf = QComboBox()
        self.pf.addItem("全部平台", "")
        self.pf.addItems(["douyin", "xiaohongshu", "kuaishou", "bilibili"])
        self.pf.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.pf)
        ab = QPushButton("+ 添加账号")
        ab.clicked.connect(self.add)
        header.addWidget(ab)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "平台", "用户名", "显示名", "状态", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        try:
            from services.account_service import AccountService
            platform = self.pf.currentData() or None
            accs = AccountService().get_accounts(platform=platform)
            self.table.setRowCount(len(accs))
            for i, a in enumerate(accs):
                self.table.setItem(i, 0, QTableWidgetItem(str(a.id)))
                self.table.setItem(i, 1, QTableWidgetItem(a.platform))
                self.table.setItem(i, 2, QTableWidgetItem(a.username))
                self.table.setItem(i, 3, QTableWidgetItem(a.display_name or ""))
                self.table.setItem(i, 4, QTableWidgetItem(a.status))
                db = QPushButton("删除")
                db.clicked.connect(lambda checked, aid=a.id: self.delete(aid))
                self.table.setCellWidget(i, 5, db)
        except Exception as e:
            logger.error(f"Account list refresh failed: {e}")

    def add(self):
        d = AccountDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.get_data()
            if data["username"]:
                from services.account_service import AccountService
                AccountService().add_account(data)
                self.refresh()

    def delete(self, aid):
        if QMessageBox.question(self, "确认", "确定删除?") == QMessageBox.Yes:
            from services.account_service import AccountService
            AccountService().delete_account(aid)
            self.refresh()
