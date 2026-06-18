"""Template management page"""
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QDialogButtonBox, QMessageBox)

logger = logging.getLogger(__name__)


class TemplateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加模板")
        self.setMinimumWidth(500)
        layout = QFormLayout(self)
        self.name = QLineEdit()
        layout.addRow("模板名称:", self.name)
        self.tp = QComboBox()
        self.tp.addItems(["comment", "reply", "dm", "like", "follow"])
        layout.addRow("动作类型:", self.tp)
        self.content = QTextEdit()
        self.content.setPlaceholderText("支持变量: {user_nickname}, {video_title}")
        self.content.setMinimumHeight(150)
        layout.addRow("模板内容:", self.content)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_data(self):
        return {"name": self.name.text().strip() or "未命名", "action_type": self.tp.currentText(), "content": self.content.toPlainText().strip()}


class TemplatePage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        header = QHBoxLayout()
        title = QLabel("话术模板")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        ab = QPushButton("+ 添加模板")
        ab.clicked.connect(self.add)
        header.addWidget(ab)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "动作类型", "内容预览"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        try:
            from models.database import get_session
            from models.template import MessageTemplate
            session = get_session()
            try:
                ts = session.query(MessageTemplate).filter(MessageTemplate.is_active == True).all()
                self.table.setRowCount(len(ts))
                for i, t in enumerate(ts):
                    self.table.setItem(i, 0, QTableWidgetItem(str(t.id)))
                    self.table.setItem(i, 1, QTableWidgetItem(t.name))
                    self.table.setItem(i, 2, QTableWidgetItem(t.action_type))
                    preview = (t.content[:80] + "...") if len(t.content) > 80 else t.content
                    self.table.setItem(i, 3, QTableWidgetItem(preview))
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Template list refresh failed: {e}")

    def add(self):
        d = TemplateDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.get_data()
            if data["content"]:
                from models.database import get_session
                from models.template import MessageTemplate
                session = get_session()
                try:
                    session.add(MessageTemplate(**data))
                    session.commit()
                finally:
                    session.close()
                self.refresh()
