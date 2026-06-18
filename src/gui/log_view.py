"""Log viewer with auto-refresh and real-time task progress"""
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QProgressBar, QTextEdit, QSplitter
)
from PySide6.QtCore import Qt, QTimer

logger = logging.getLogger(__name__)


class LogPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QHBoxLayout()
        title = QLabel("\U0001f4dc 运行日志")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #89b4fa;")
        header.addWidget(title)
        header.addStretch()

        self.auto_refresh = True
        self.auto_btn = QPushButton("⏸ 暂停刷新")
        self.auto_btn.setStyleSheet(
            "QPushButton{background-color:#45475a;border:none;border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background-color:#585b70;}"
        )
        self.auto_btn.clicked.connect(self._toggle_auto)
        header.addWidget(self.auto_btn)

        self.level_filter = QComboBox()
        self.level_filter.addItem("全部级别", "")
        self.level_filter.addItems(["info", "warning", "error", "debug"])
        self.level_filter.currentIndexChanged.connect(self.refresh)
        header.addWidget(self.level_filter)

        rb = QPushButton("\U0001f504 刷新")
        rb.clicked.connect(self.refresh)
        header.addWidget(rb)
        layout.addLayout(header)

        # Main content: splitter with log table + task progress
        splitter = QSplitter(Qt.Vertical)

        # Log table
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["时间", "级别", "任务ID", "消息"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        log_layout.addWidget(self.table)
        splitter.addWidget(log_widget)

        # Task progress panel
        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)

        prog_header = QHBoxLayout()
        prog_label = QLabel("\U0001f4ca 任务实时进度")
        prog_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #a6adc8;")
        prog_header.addWidget(prog_label)
        prog_header.addStretch()
        progress_layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setStyleSheet(
            "QProgressBar{border:1px solid #45475a;border-radius:4px;text-align:center;color:#cdd6f4;}"
            "QProgressBar::chunk{background-color:#89b4fa;border-radius:3px;}"
        )
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        self.task_log = QTextEdit()
        self.task_log.setReadOnly(True)
        self.task_log.setStyleSheet(
            "background-color:#181825;border:1px solid #313244;border-radius:4px;"
            "font-family:Consolas,monospace;font-size:12px;color:#cdd6f4;"
        )
        self.task_log.setPlaceholderText("选择正在运行的任务查看实时日志...")
        progress_layout.addWidget(self.task_log)

        splitter.addWidget(progress_widget)
        splitter.setSizes([400, 300])
        layout.addWidget(splitter)

        # Auto-refresh timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)  # 3 seconds

        self.refresh()

    def _toggle_auto(self):
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            self.auto_btn.setText("⏸ 暂停刷新")
            self.timer.start(3000)
        else:
            self.auto_btn.setText("▶ 恢复刷新")
            self.timer.stop()

    def refresh(self):
        self._refresh_log_table()
        self._refresh_task_progress()

    def _refresh_log_table(self):
        try:
            from models.database import get_session
            from models.audit import ExecutionLog
            session = get_session()
            try:
                q = session.query(ExecutionLog)
                level = self.level_filter.currentData()
                if level:
                    q = q.filter(ExecutionLog.level == level)
                logs = q.order_by(ExecutionLog.created_at.desc()).limit(200).all()
                self.table.setRowCount(len(logs))
                for i, l in enumerate(logs):
                    time_str = l.created_at.strftime("%m-%d %H:%M:%S") if l.created_at else ""
                    self.table.setItem(i, 0, QTableWidgetItem(time_str))

                    level_item = QTableWidgetItem(l.level)
                    if l.level == "error":
                        level_item.setForeground(Qt.red)
                    elif l.level == "warning":
                        level_item.setForeground(Qt.yellow)
                    else:
                        level_item.setForeground(Qt.green)
                    self.table.setItem(i, 1, level_item)

                    self.table.setItem(i, 2, QTableWidgetItem(str(l.task_id or "-")))
                    self.table.setItem(i, 3, QTableWidgetItem(l.message[:120] if l.message else ""))
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Log refresh failed: {e}")

    def _refresh_task_progress(self):
        """Show real-time progress for running tasks."""
        try:
            from models.database import get_session
            from models.task import Task
            session = get_session()
            try:
                running = session.query(Task).filter(
                    Task.status == "running").order_by(Task.updated_at.desc()).first()
                if running:
                    pct = running.progress_percent
                    self.progress_bar.setValue(int(pct))
                    self.progress_bar.setFormat(
                        f"{running.name} - {running.progress_done}/{running.progress_total} ({pct}%)")

                    # Get real-time logs from TaskExecutor if available
                    try:
                        from services.task_executor import TaskExecutor
                        executor = TaskExecutor()
                        logs = executor.get_task_logs(running.id, limit=50)
                        if logs:
                            lines = []
                            for entry in logs:
                                lines.append(
                                    f"[{entry['time']}] [{entry['level'].upper()}] {entry['message']}")
                            self.task_log.setPlainText("\n".join(lines))
                            self.task_log.verticalScrollBar().setValue(
                                self.task_log.verticalScrollBar().maximum())
                    except Exception:
                        pass
                else:
                    self.progress_bar.setValue(0)
                    self.progress_bar.setFormat("无运行中的任务")
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Progress refresh failed: {e}")
