"""风控中心页面"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QDialogButtonBox, QMessageBox, QTextEdit
)

logger = logging.getLogger(__name__)


class AddRuleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加风控规则")
        self.setMinimumWidth(450)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit()
        layout.addRow("规则名称:", self.name_edit)
        self.type_combo = QComboBox()
        self.type_combo.addItems(["daily_limit", "hourly_limit", "per_video_limit", "cooldown", "circuit_breaker"])
        layout.addRow("规则类型:", self.type_combo)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["all", "douyin", "xiaohongshu", "kuaishou", "bilibili"])
        layout.addRow("平台:", self.platform_combo)
        self.action_combo = QComboBox()
        self.action_combo.addItems(["all", "comment", "reply", "like", "follow", "dm", "favorite"])
        layout.addRow("操作类型:", self.action_combo)
        self.config_edit = QTextEdit()
        self.config_edit.setPlaceholderText('{"max_per_day": 50, "max_per_hour": 10}')
        self.config_edit.setMaximumHeight(80)
        layout.addRow("配置JSON:", self.config_edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_data(self):
        import json
        config_str = self.config_edit.toPlainText().strip() or "{}"
        try:
            config = json.loads(config_str)
        except json.JSONDecodeError:
            config = {}
        return {
            "name": self.name_edit.text().strip(),
            "rule_type": self.type_combo.currentText(),
            "platform": self.platform_combo.currentText(),
            "action_type": self.action_combo.currentText(),
            "config_json": json.dumps(config, ensure_ascii=False),
        }


class AddSensitiveWordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加敏感词")
        self.setMinimumWidth(350)
        layout = QFormLayout(self)
        self.word_edit = QLineEdit()
        layout.addRow("敏感词:", self.word_edit)
        self.category_combo = QComboBox()
        self.category_combo.addItems(["general", "ad", "abuse", "political", "other"])
        layout.addRow("分类:", self.category_combo)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_data(self):
        return {"word": self.word_edit.text().strip(), "category": self.category_combo.currentText()}


class AddBlacklistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加黑名单")
        self.setMinimumWidth(350)
        layout = QFormLayout(self)
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["douyin", "xiaohongshu", "kuaishou", "bilibili"])
        layout.addRow("平台:", self.platform_combo)
        self.uid_edit = QLineEdit()
        layout.addRow("用户ID:", self.uid_edit)
        self.reason_edit = QLineEdit()
        layout.addRow("原因:", self.reason_edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_data(self):
        return {
            "platform": self.platform_combo.currentText(),
            "user_id": self.uid_edit.text().strip(),
            "reason": self.reason_edit.text().strip(),
        }


class RiskPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("🛡️ 风控中心")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: 风控规则
        rules_tab = QWidget()
        rl = QVBoxLayout(rules_tab)
        rh = QHBoxLayout()
        rh.addStretch()
        add_rule_btn = QPushButton("+ 添加规则")
        add_rule_btn.clicked.connect(self.add_rule)
        rh.addWidget(add_rule_btn)
        rl.addLayout(rh)
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(7)
        self.rules_table.setHorizontalHeaderLabels(["ID", "名称", "类型", "平台", "操作", "配置", "操作"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rules_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.rules_table.setEditTriggers(QTableWidget.NoEditTriggers)
        rl.addWidget(self.rules_table)
        self.tabs.addTab(rules_tab, "风控规则")

        # Tab 2: 敏感词
        sw_tab = QWidget()
        swl = QVBoxLayout(sw_tab)
        swh = QHBoxLayout()
        swh.addStretch()
        add_sw_btn = QPushButton("+ 添加敏感词")
        add_sw_btn.clicked.connect(self.add_sensitive_word)
        swh.addWidget(add_sw_btn)
        swl.addLayout(swh)
        self.sw_table = QTableWidget()
        self.sw_table.setColumnCount(5)
        self.sw_table.setHorizontalHeaderLabels(["ID", "敏感词", "分类", "状态", "操作"])
        self.sw_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.sw_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sw_table.setEditTriggers(QTableWidget.NoEditTriggers)
        swl.addWidget(self.sw_table)
        self.tabs.addTab(sw_tab, "敏感词库")

        # Tab 3: 黑名单
        bl_tab = QWidget()
        bll = QVBoxLayout(bl_tab)
        blh = QHBoxLayout()
        blh.addStretch()
        add_bl_btn = QPushButton("+ 添加黑名单")
        add_bl_btn.clicked.connect(self.add_blacklist)
        blh.addWidget(add_bl_btn)
        bll.addLayout(blh)
        self.bl_table = QTableWidget()
        self.bl_table.setColumnCount(5)
        self.bl_table.setHorizontalHeaderLabels(["ID", "平台", "用户ID", "原因", "操作"])
        self.bl_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.bl_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.bl_table.setEditTriggers(QTableWidget.NoEditTriggers)
        bll.addWidget(self.bl_table)
        self.tabs.addTab(bl_tab, "黑名单")

        self.refresh_all()

    def refresh_all(self):
        self.refresh_rules()
        self.refresh_sensitive_words()
        self.refresh_blacklist()

    def refresh_rules(self):
        try:
            from services.risk_service import RiskService
            rules = RiskService().get_risk_rules()
            self.rules_table.setRowCount(len(rules))
            for i, r in enumerate(rules):
                self.rules_table.setItem(i, 0, QTableWidgetItem(str(r.id)))
                self.rules_table.setItem(i, 1, QTableWidgetItem(r.name))
                self.rules_table.setItem(i, 2, QTableWidgetItem(r.rule_type))
                self.rules_table.setItem(i, 3, QTableWidgetItem(r.platform))
                self.rules_table.setItem(i, 4, QTableWidgetItem(r.action_type))
                self.rules_table.setItem(i, 5, QTableWidgetItem(r.config_json or "{}"))
                db = QPushButton("删除")
                db.clicked.connect(lambda checked, rid=r.id: self.delete_rule(rid))
                self.rules_table.setCellWidget(i, 6, db)
        except Exception as e:
            logger.error(f"Risk rules refresh failed: {e}")

    def refresh_sensitive_words(self):
        try:
            from services.risk_service import RiskService
            words = RiskService().get_sensitive_words()
            self.sw_table.setRowCount(len(words))
            for i, w in enumerate(words):
                self.sw_table.setItem(i, 0, QTableWidgetItem(str(w.id)))
                self.sw_table.setItem(i, 1, QTableWidgetItem(w.word))
                self.sw_table.setItem(i, 2, QTableWidgetItem(w.category))
                self.sw_table.setItem(i, 3, QTableWidgetItem("启用" if w.is_active else "禁用"))
                db = QPushButton("删除")
                db.clicked.connect(lambda checked, wid=w.id: self.delete_sensitive_word(wid))
                self.sw_table.setCellWidget(i, 4, db)
        except Exception as e:
            logger.error(f"Sensitive words refresh failed: {e}")

    def refresh_blacklist(self):
        try:
            from services.risk_service import RiskService
            bls = RiskService().get_blacklist()
            self.bl_table.setRowCount(len(bls))
            for i, b in enumerate(bls):
                self.bl_table.setItem(i, 0, QTableWidgetItem(str(b.id)))
                self.bl_table.setItem(i, 1, QTableWidgetItem(b.platform))
                self.bl_table.setItem(i, 2, QTableWidgetItem(b.user_id))
                self.bl_table.setItem(i, 3, QTableWidgetItem(b.reason or ""))
                db = QPushButton("移除")
                db.clicked.connect(lambda checked, bid=b.id: self.delete_blacklist(bid))
                self.bl_table.setCellWidget(i, 4, db)
        except Exception as e:
            logger.error(f"Blacklist refresh failed: {e}")

    def add_rule(self):
        d = AddRuleDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.get_data()
            if data["name"]:
                from services.risk_service import RiskService
                RiskService().add_risk_rule(data)
                self.refresh_rules()

    def add_sensitive_word(self):
        d = AddSensitiveWordDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.get_data()
            if data["word"]:
                from services.risk_service import RiskService
                RiskService().add_sensitive_word(data["word"], data["category"])
                self.refresh_sensitive_words()

    def add_blacklist(self):
        d = AddBlacklistDialog(self)
        if d.exec() == QDialog.Accepted:
            data = d.get_data()
            if data["user_id"]:
                from services.risk_service import RiskService
                RiskService().add_to_blacklist(data["platform"], data["user_id"], data["reason"])
                self.refresh_blacklist()

    def delete_rule(self, rid):
        if QMessageBox.question(self, "确认", "确定删除该规则?") == QMessageBox.Yes:
            from services.risk_service import RiskService
            RiskService().delete_risk_rule(rid)
            self.refresh_rules()

    def delete_sensitive_word(self, wid):
        if QMessageBox.question(self, "确认", "确定删除该敏感词?") == QMessageBox.Yes:
            from services.risk_service import RiskService
            RiskService().delete_sensitive_word(wid)
            self.refresh_sensitive_words()

    def delete_blacklist(self, bid):
        if QMessageBox.question(self, "确认", "确定从黑名单移除?") == QMessageBox.Yes:
            from services.risk_service import RiskService
            RiskService().remove_from_blacklist(bid)
            self.refresh_blacklist()
