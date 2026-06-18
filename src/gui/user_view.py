"""User management admin page."""
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout,
    QLineEdit, QComboBox, QSpinBox, QMessageBox, QLabel,
    QTextEdit, QHeaderView, QDateEdit
)
from PySide6.QtCore import Qt, QDate
from services.user_service import UserService


class AddEditUserDialog(QDialog):
    def __init__(self, parent=None, user=None):
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("编辑用户" if user else "新增用户")
        self.setFixedSize(420, 520)
        self._result = None
        self._build_ui()
        if user:
            self._populate()

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(30, 20, 30, 20)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("登录用户名")
        layout.addRow("用户名:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("留空则不修改" if self.user else "登录密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addRow("密码:", self.password_input)

        self.nickname_input = QLineEdit()
        self.nickname_input.setPlaceholderText("显示名称")
        layout.addRow("昵称:", self.nickname_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("手机号码")
        layout.addRow("手机号:", self.phone_input)

        self.position_input = QLineEdit()
        self.position_input.setPlaceholderText("职位/岗位")
        layout.addRow("职位:", self.position_input)

        self.role_combo = QComboBox()
        self.role_combo.addItems(["user", "admin"])
        layout.addRow("角色:", self.role_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["active", "disabled"])
        layout.addRow("状态:", self.status_combo)

        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 36500)
        self.days_spin.setValue(30)
        self.days_spin.setSuffix(" 天")
        layout.addRow("使用期限:", self.days_spin)

        self.expire_date = QDateEdit()
        self.expire_date.setCalendarPopup(True)
        self.expire_date.setDate(QDate.currentDate().addDays(30))
        layout.addRow("到期时间:", self.expire_date)

        self.remark_input = QTextEdit()
        self.remark_input.setPlaceholderText("备注信息")
        self.remark_input.setFixedHeight(50)
        layout.addRow("备注:", self.remark_input)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("QPushButton{background-color:#89b4fa;color:#1e1e2e;border:none;border-radius:6px;padding:8px 20px;font-weight:bold;}QPushButton:hover{background-color:#74c7ec;}")
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addRow("", btn_layout)

    def _populate(self):
        self.username_input.setText(self.user.username)
        self.username_input.setReadOnly(True)
        self.nickname_input.setText(self.user.nickname or "")
        self.phone_input.setText(self.user.phone or "")
        self.position_input.setText(self.user.position or "")
        self.role_combo.setCurrentText(self.user.role)
        self.status_combo.setCurrentText(self.user.status)
        self.days_spin.setValue(self.user.usage_days or 30)
        if self.user.expire_at:
            self.expire_date.setDate(QDate(self.user.expire_at.year,
                                           self.user.expire_at.month,
                                           self.user.expire_at.day))
        self.remark_input.setPlainText(self.user.remark or "")

    def _on_save(self):
        username = self.username_input.text().strip()
        if not username:
            QMessageBox.warning(self, "错误", "用户名不能为空")
            return
        if not self.user and not self.password_input.text():
            QMessageBox.warning(self, "错误", "新用户必须设置密码")
            return
        self._result = {
            "username": username,
            "password": self.password_input.text() or None,
            "nickname": self.nickname_input.text().strip(),
            "phone": self.phone_input.text().strip(),
            "position": self.position_input.text().strip(),
            "role": self.role_combo.currentText(),
            "status": self.status_combo.currentText(),
            "usage_days": self.days_spin.value(),
            "expire_at": datetime(
                self.expire_date.date().year(),
                self.expire_date.date().month(),
                self.expire_date.date().day(),
            ),
            "remark": self.remark_input.toPlainText().strip(),
        }
        self.accept()


class UserPage(QWidget):
    def __init__(self):
        super().__init__()
        self.user_service = UserService()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QHBoxLayout()
        title = QLabel("\U0001f465 用户管理")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #89b4fa;")
        header.addWidget(title)
        header.addStretch()

        add_btn = QPushButton("+ 新增用户")
        add_btn.setStyleSheet("QPushButton{background-color:#a6e3a1;color:#1e1e2e;border:none;border-radius:6px;padding:8px 16px;font-weight:bold;}QPushButton:hover{background-color:#94e2d5;}")
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            ["ID", "用户名", "昵称", "手机号", "职位", "角色", "状态", "到期时间", "剩余天数", "操作"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

    def refresh(self):
        users = self.user_service.list_users()
        self.table.setRowCount(len(users))
        for row, u in enumerate(users):
            self.table.setItem(row, 0, QTableWidgetItem(str(u.id)))
            self.table.setItem(row, 1, QTableWidgetItem(u.username))
            self.table.setItem(row, 2, QTableWidgetItem(u.nickname or ""))
            self.table.setItem(row, 3, QTableWidgetItem(u.phone or ""))
            self.table.setItem(row, 4, QTableWidgetItem(u.position or ""))
            self.table.setItem(row, 5, QTableWidgetItem(u.role))

            status_item = QTableWidgetItem(u.status)
            if u.is_expired():
                status_item.setText("已过期")
                status_item.setForeground(Qt.red)
            elif u.status == "disabled":
                status_item.setForeground(Qt.yellow)
            else:
                status_item.setForeground(Qt.green)
            self.table.setItem(row, 6, status_item)

            expire_str = u.expire_at.strftime("%Y-%m-%d %H:%M") if u.expire_at else "无期限"
            self.table.setItem(row, 7, QTableWidgetItem(expire_str))

            days = u.days_remaining()
            days_str = str(days) if days >= 0 else "永久"
            days_item = QTableWidgetItem(days_str)
            if 0 <= days <= 7:
                days_item.setForeground(Qt.red)
            elif 0 <= days <= 30:
                days_item.setForeground(Qt.yellow)
            self.table.setItem(row, 8, days_item)

            ops = QWidget()
            ops_layout = QHBoxLayout(ops)
            ops_layout.setContentsMargins(4, 2, 4, 2)
            edit_btn = QPushButton("编辑")
            edit_btn.setFixedHeight(28)
            edit_btn.setStyleSheet("QPushButton{background-color:#45475a;border:none;border-radius:4px;padding:2px 10px;}QPushButton:hover{background-color:#585b70;}")
            edit_btn.clicked.connect(lambda _, uid=u.id: self._on_edit(uid))
            del_btn = QPushButton("删除")
            del_btn.setFixedHeight(28)
            del_btn.setStyleSheet("QPushButton{background-color:#f38ba8;color:#1e1e2e;border:none;border-radius:4px;padding:2px 10px;}QPushButton:hover{background-color:#eba0ac;}")
            del_btn.clicked.connect(lambda _, uid=u.id, name=u.username: self._on_delete(uid, name))
            ops_layout.addWidget(edit_btn)
            ops_layout.addWidget(del_btn)
            self.table.setCellWidget(row, 9, ops)

    def _on_add(self):
        dlg = AddEditUserDialog(self)
        if dlg.exec() == QDialog.Accepted:
            r = dlg._result
            try:
                self.user_service.create_user(
                    username=r["username"], password=r["password"],
                    nickname=r["nickname"], role=r["role"],
                    usage_days=r["usage_days"], phone=r["phone"],
                    position=r["position"], remark=r["remark"],
                )
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "错误", str(e))

    def _on_edit(self, user_id):
        user = self.user_service.get_user(user_id)
        if not user:
            return
        dlg = AddEditUserDialog(self, user=user)
        if dlg.exec() == QDialog.Accepted:
            r = dlg._result
            try:
                self.user_service.update_user(user_id, **r)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "错误", str(e))

    def _on_delete(self, user_id, username):
        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除用户 \'{username}\' 吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.user_service.delete_user(user_id)
                self.refresh()
            except ValueError as e:
                QMessageBox.warning(self, "错误", str(e))
