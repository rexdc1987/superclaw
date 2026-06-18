"""Playbook view — 打法模板管理页面"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGridLayout, QScrollArea, QMessageBox, QDialog,
    QFormLayout, QLineEdit, QTextEdit, QComboBox,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

STYLE_CARD = (
    "QFrame{background-color:#313244;border-radius:12px;padding:16px;}"
    "QFrame:hover{background-color:#45475a;}"
)
STYLE_CARD_ACTIVE = (
    "QFrame{background-color:#45475a;border-radius:12px;padding:16px;"
    "border:2px solid #89b4fa;}"
)
RISK_COLORS = {"low": "#a6e3a1", "medium": "#f9e2af", "high": "#f38ba8"}


class PlaybookCard(QFrame):
    def __init__(self, preset, on_click):
        super().__init__()
        self.preset = preset
        self.on_click = on_click
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(160)
        self.setStyleSheet(STYLE_CARD)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        top = QHBoxLayout()
        icon = QLabel(self.preset.get("icon", "📋"))
        icon.setStyleSheet("font-size:28px;")
        top.addWidget(icon)
        name = QLabel(self.preset["name"])
        name.setStyleSheet("font-size:16px;font-weight:bold;color:#cdd6f4;")
        top.addWidget(name)
        top.addStretch()
        risk = self.preset.get("risk_level", "low")
        risk_label = QLabel(f"风险: {risk}")
        risk_label.setStyleSheet(f"color:{RISK_COLORS.get(risk,'#a6adc8')};font-size:11px;")
        top.addWidget(risk_label)
        layout.addLayout(top)

        desc = QLabel(self.preset.get("description", ""))
        desc.setStyleSheet("color:#a6adc8;font-size:12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        scenario = QLabel(f"📌 适用场景: {self.preset.get('scenario', '-')}")
        scenario.setStyleSheet("color:#89b4fa;font-size:11px;")
        layout.addWidget(scenario)

        actions = self.preset.get("action_config", {}).get("action_types", [])
        action_labels = {"comment": "💬评论", "dm": "📩私信", "like": "👍点赞",
                         "follow": "➕关注", "favorite": "⭐收藏"}
        action_str = " ".join(action_labels.get(a, a) for a in actions)
        act_label = QLabel(f"⚡ 动作: {action_str}")
        act_label.setStyleSheet("color:#bac2de;font-size:11px;")
        layout.addWidget(act_label)

    def set_selected(self, selected):
        self._selected = selected
        self.setStyleSheet(STYLE_CARD_ACTIVE if selected else STYLE_CARD)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_click(self.preset)
        super().mousePressEvent(event)


class PlaybookPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("🎯 打法模板")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        add_btn = QPushButton("+ 自定义打法")
        add_btn.clicked.connect(self._add_playbook)
        header.addWidget(add_btn)
        layout.addLayout(header)

        subtitle = QLabel("选择一套预设打法快速创建任务，或自定义打法模板")
        subtitle.setStyleSheet("color:#a6adc8;font-size:13px;")
        layout.addWidget(subtitle)

        # Preset cards grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        cards_widget = QWidget()
        self.cards_layout = QGridLayout(cards_widget)
        self.cards_layout.setSpacing(12)
        scroll.setWidget(cards_widget)
        layout.addWidget(scroll, 1)

        # Custom playbooks table
        custom_label = QLabel("📋 自定义打法")
        custom_label.setStyleSheet("font-size:14px;font-weight:bold;color:#a6adc8;")
        layout.addWidget(custom_label)

        self.custom_table = QTableWidget()
        self.custom_table.setColumnCount(5)
        self.custom_table.setHorizontalHeaderLabels(["ID", "名称", "类型", "风险", "操作"])
        self.custom_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.custom_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.custom_table.setMaximumHeight(180)
        layout.addWidget(self.custom_table)

        self._selected_preset = None
        self._load_presets()
        self._refresh_custom()

    def _load_presets(self):
        from services.playbook_service import PlaybookService
        presets = PlaybookService().get_preset_playbooks()
        for idx, preset in enumerate(presets):
            card = PlaybookCard(preset, self._on_card_click)
            row, col = divmod(idx, 3)
            self.cards_layout.addWidget(card, row, col)

    def _on_card_click(self, preset):
        self._selected_preset = preset
        # Update card selection visual
        for i in range(self.cards_layout.count()):
            w = self.cards_layout.itemAt(i).widget()
            if isinstance(w, PlaybookCard):
                w.set_selected(w.preset == preset)

        reply = QMessageBox.question(
            self, "创建任务",
            f"使用打法「{preset['name']}」快速创建任务？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._create_task_from_preset(preset)

    def _create_task_from_preset(self, preset):
        try:
            from services.task_service import TaskService
            svc = TaskService()
            task = svc.create_task({
                "name": preset["name"],
                "platform": "douyin",
                "search_config_json": str(preset.get("search_config", {})).replace("'", '"'),
                "filter_config_json": str(preset.get("filter_config", {})).replace("'", '"'),
                "action_config_json": str(preset.get("action_config", {})).replace("'", '"'),
            })
            # Apply preset configs properly via JSON
            from services.playbook_service import PlaybookService
            PlaybookService().apply_preset_to_task(task.id, preset["playbook_type"])
            QMessageBox.information(self, "成功", f"任务已创建 (ID: {task.id})，可在任务中心查看")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def _add_playbook(self):
        d = AddPlaybookDialog(self)
        if d.exec() == QDialog.Accepted:
            from services.playbook_service import PlaybookService
            PlaybookService().create_playbook(d.get_data())
            self._refresh_custom()

    def _refresh_custom(self):
        try:
            from services.playbook_service import PlaybookService
            pbs = PlaybookService().get_playbooks(active_only=False)
            self.custom_table.setRowCount(len(pbs))
            for i, pb in enumerate(pbs):
                self.custom_table.setItem(i, 0, QTableWidgetItem(str(pb.id)))
                self.custom_table.setItem(i, 1, QTableWidgetItem(pb.name))
                self.custom_table.setItem(i, 2, QTableWidgetItem(pb.playbook_type))
                self.custom_table.setItem(i, 3, QTableWidgetItem(pb.risk_level))
                db = QPushButton("删除")
                db.clicked.connect(lambda checked, pid=pb.id: self._delete(pid))
                self.custom_table.setCellWidget(i, 4, db)
        except Exception as e:
            logger.error(f"Custom playbooks refresh failed: {e}")

    def _delete(self, pid):
        if QMessageBox.question(self, "确认", "确定删除该打法？") == QMessageBox.Yes:
            from services.playbook_service import PlaybookService
            PlaybookService().delete_playbook(pid)
            self._refresh_custom()


class AddPlaybookDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加自定义打法")
        self.setMinimumWidth(450)
        layout = QFormLayout(self)
        self.name = QLineEdit()
        layout.addRow("打法名称:", self.name)
        self.desc = QTextEdit()
        self.desc.setMaximumHeight(60)
        layout.addRow("描述:", self.desc)
        self.ptype = QComboBox()
        self.ptype.addItems(["auto_exposure", "targeted_exposure", "link_exposure",
                             "account_search", "stealth_exposure"])
        layout.addRow("类型:", self.ptype)
        self.risk = QComboBox()
        self.risk.addItems(["low", "medium", "high"])
        layout.addRow("风险等级:", self.risk)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_data(self):
        return {
            "name": self.name.text().strip() or "未命名打法",
            "description": self.desc.toPlainText().strip(),
            "playbook_type": self.ptype.currentText(),
            "risk_level": self.risk.currentText(),
            "is_active": True,
        }
