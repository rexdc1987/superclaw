"""Task management page"""
import json
import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QSpinBox, QDialogButtonBox, QMessageBox, QProgressBar,
    QTabWidget, QCheckBox, QGroupBox, QGridLayout, QFrame)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)

ACTION_TYPES = ["comment", "like", "favorite", "follow"]
ACTION_LABELS = {
    "comment": "💬 评论", "like": "👍 点赞",
    "favorite": "⭐ 收藏", "follow": "➕ 关注",
}


class TaskDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建任务")
        self.setMinimumWidth(680)
        self.setMinimumHeight(640)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── 基本信息 ──
        base = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("为任务取个名字")
        base.addRow("任务名称:", self.name)
        self.pf = QComboBox()
        self.pf.addItems(["douyin", "xiaohongshu", "kuaishou", "bilibili"])
        base.addRow("平台:", self.pf)
        root.addLayout(base)

        # ── Tab 区 ──
        tabs = QTabWidget()
        tabs.addTab(self._build_rhythm_tab(), "🎵 节奏控制")
        tabs.addTab(self._build_filter_tab(), "🔍 筛选配置")
        tabs.addTab(self._build_action_tab(), "⚡ 动作配置")
        tabs.addTab(self._build_template_tab(), "📝 话术模板")
        root.addWidget(tabs, 1)

        # ── 底部按钮 ──
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    # ────────────── Tab 1: 节奏控制 ──────────────
    def _build_rhythm_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self.interval_min = self._spin(form, "评论间隔最小 (秒):", 1, 300, 5)
        self.interval_max = self._spin(form, "评论间隔最大 (秒):", 1, 600, 10)
        self.rest_after = self._spin(form, "执行 N 次后休息:", 0, 500, 10,
                                     tooltip="设为 0 则不休息")
        self.rest_min = self._spin(form, "休息时长最小 (秒):", 1, 3600, 60)
        self.rest_max = self._spin(form, "休息时长最大 (秒):", 1, 3600, 200)
        self.rotate_after = self._spin(form, "每 N 次换关键词:", 0, 200, 5,
                                        tooltip="设为 0 则不轮换")

        hint = QLabel("💡 间隔/休息时长为区间随机值，避免行为机械化。")
        hint.setStyleSheet("color:#a6adc8;font-size:11px;")
        form.addRow(hint)
        return w

    # ────────────── Tab 2: 筛选配置 ──────────────
    def _build_filter_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        # 关键词
        self.kw = QTextEdit()
        self.kw.setPlaceholderText("每行一个关键词，匹配评论内容")
        self.kw.setMaximumHeight(80)
        form.addRow("关键词:", self.kw)

        self.max_comments = self._spin(form, "每视频最多采集数:", 1, 2000, 50)
        self.time_days = self._spin(form, "时间范围 (天):", 0, 365, 0,
                                    tooltip="0 = 不限时间")
        self.exclude_regions = QLineEdit()
        self.exclude_regions.setPlaceholderText("逗号分隔，如: 北京,上海,广东")
        form.addRow("排除地区:", self.exclude_regions)

        self.exclude_words = QLineEdit()
        self.exclude_words.setPlaceholderText("逗号分隔，排除含这些词的评论")
        form.addRow("排除关键词:", self.exclude_words)

        hint = QLabel("💡 排除地区/关键词均对评论作者昵称或内容生效。")
        hint.setStyleSheet("color:#a6adc8;font-size:11px;")
        form.addRow(hint)
        return w

    # ────────────── Tab 3: 动作配置 ──────────────
    def _build_action_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        # 多选动作类型
        action_group = QGroupBox("动作类型 (可多选)")
        action_grid = QGridLayout(action_group)
        self.action_checks = {}
        for idx, atype in enumerate(ACTION_TYPES):
            cb = QCheckBox(ACTION_LABELS[atype])
            cb.setProperty("action_type", atype)
            if atype == "comment":
                cb.setChecked(True)
            self.action_checks[atype] = cb
            action_grid.addWidget(cb, idx // 2, idx % 2)
        form.addRow(action_group)

        self.mention_user = QLineEdit()
        self.mention_user.setPlaceholderText("@的目标用户名，留空则不@")
        form.addRow("@ 用户:", self.mention_user)

        return w

    # ────────────── Tab 4: 话术模板 ──────────────
    def _build_template_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self.template_ids = QLineEdit()
        self.template_ids.setPlaceholderText("逗号分隔的模板ID，如: 1,2,3")
        form.addRow("模板 ID:", self.template_ids)

        hint = QLabel(
            "💡 系统会从这些模板中随机抽取分配给各动作，避免话术重复。\n"
            "留空则使用动作配置中的默认内容。"
        )
        hint.setStyleSheet("color:#a6adc8;font-size:11px;")
        hint.setWordWrap(True)
        form.addRow(hint)
        return w

    # ── 工具方法 ──
    def _spin(self, form, label, lo, hi, default, tooltip=None):
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setValue(default)
        if tooltip:
            sp.setToolTip(tooltip)
        form.addRow(label, sp)
        return sp

    # ── 组装数据 ──
    def _get_rhythm_config(self):
        return {
            "interval_min": self.interval_min.value(),
            "interval_max": self.interval_max.value(),
            "rest_after": self.rest_after.value(),
            "rest_min": self.rest_min.value(),
            "rest_max": self.rest_max.value(),
            "keyword_rotate_after": self.rotate_after.value(),
        }

    def _get_filter_config(self):
        kws = [k.strip() for k in self.kw.toPlainText().splitlines() if k.strip()]
        regions = [r.strip() for r in self.exclude_regions.text().split(",") if r.strip()]
        exc_words = [w.strip() for w in self.exclude_words.text().split(",") if w.strip()]
        cfg = {"keywords": kws}
        if self.max_comments.value() != 50:
            cfg["max_comments_per_video"] = self.max_comments.value()
        if self.time_days.value() > 0:
            cfg["time_range_days"] = self.time_days.value()
        if regions:
            cfg["exclude_regions"] = regions
        if exc_words:
            cfg["exclude_words"] = exc_words
        return cfg

    def _get_action_config(self):
        selected = [at for at, cb in self.action_checks.items() if cb.isChecked()]
        cfg = {
            "action_types": selected if selected else ["comment"],
        }
        mention = self.mention_user.text().strip()
        if mention:
            cfg["mention_user"] = mention
        # Template IDs
        raw_ids = self.template_ids.text().strip()
        if raw_ids:
            try:
                tids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
                cfg["template_ids"] = tids
            except ValueError:
                pass  # 非数字 ID 忽略
        return cfg

    def get_data(self):
        return {
            "name": self.name.text().strip() or "未命名",
            "platform": self.pf.currentText(),
            "search_config_json": json.dumps({
                "video_count": 10,
                "comment_count": self.max_comments.value(),
            }, ensure_ascii=False),
            "filter_config_json": json.dumps(self._get_filter_config(), ensure_ascii=False),
            "rhythm_config_json": json.dumps(self._get_rhythm_config(), ensure_ascii=False),
            "action_config_json": json.dumps(self._get_action_config(), ensure_ascii=False),
        }


class TaskPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        header = QHBoxLayout()
        title = QLabel("任务中心")
        title.setStyleSheet("font-size:24px;font-weight:bold;")
        header.addWidget(title)
        header.addStretch()
        self.sf = QComboBox()
        self.sf.addItem("全部状态", "")
        self.sf.addItems(["draft", "pending", "running", "paused", "completed", "failed"])
        self.sf.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.sf)
        cb = QPushButton("+ 创建任务")
        cb.clicked.connect(self.create)
        header.addWidget(cb)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["ID", "名称", "平台", "状态", "进度", "创建时间", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        try:
            from services.task_service import TaskService
            status = self.sf.currentData() or None
            tasks = TaskService().get_tasks(status=status)
            self.table.setRowCount(len(tasks))
            for i, t in enumerate(tasks):
                self.table.setItem(i, 0, QTableWidgetItem(str(t.id)))
                self.table.setItem(i, 1, QTableWidgetItem(t.name))
                self.table.setItem(i, 2, QTableWidgetItem(t.platform))
                self.table.setItem(i, 3, QTableWidgetItem(t.status))
                pb = QProgressBar()
                pb.setValue(int(t.progress_percent))
                self.table.setCellWidget(i, 4, pb)
                self.table.setItem(i, 5, QTableWidgetItem(
                    t.created_at.strftime("%m-%d %H:%M") if t.created_at else ""))
                ops = QWidget()
                ol = QHBoxLayout(ops)
                ol.setContentsMargins(0, 0, 0, 0)
                if t.status in ("draft", "pending"):
                    sb = QPushButton("启动")
                    sb.clicked.connect(lambda checked, tid=t.id: self.start(tid))
                    ol.addWidget(sb)
                elif t.status == "running":
                    pb2 = QPushButton("暂停")
                    pb2.clicked.connect(lambda checked, tid=t.id: self.pause(tid))
                    ol.addWidget(pb2)
                self.table.setCellWidget(i, 6, ops)
        except Exception as e:
            logger.error(f"Task list refresh failed: {e}")

    def create(self):
        d = TaskDialog(self)
        if d.exec() == QDialog.Accepted:
            from services.task_service import TaskService
            TaskService().create_task(d.get_data())
            self.refresh()

    def start(self, tid):
        try:
            from services.task_service import TaskService
            TaskService().update_task(tid, {"status": "pending"})
            TaskService().start_task(tid)
            self.refresh()
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def pause(self, tid):
        try:
            from services.task_service import TaskService
            TaskService().pause_task(tid)
            self.refresh()
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))
