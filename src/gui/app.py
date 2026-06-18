"""SuperClaw GUI Application"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__))))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
import models
from models.database import init_db

DARK_STYLE = """
QMainWindow { background-color: #1e1e2e; }
QWidget { background-color: #1e1e2e; color: #cdd6f4; font-family: "Microsoft YaHei"; font-size: 13px; }
QPushButton { background-color: #313244; border: 1px solid #45475a; border-radius: 6px; padding: 8px 16px; color: #cdd6f4; }
QPushButton:hover { background-color: #45475a; }
QTableWidget { background-color: #181825; border: 1px solid #313244; gridline-color: #313244; }
QTableWidget::item:selected { background-color: #45475a; }
QHeaderView::section { background-color: #313244; color: #cdd6f4; padding: 6px; border: 1px solid #45475a; }
QLineEdit, QTextEdit, QComboBox, QSpinBox { background-color: #313244; border: 1px solid #45475a; border-radius: 4px; padding: 6px; color: #cdd6f4; }
QLabel { color: #cdd6f4; }
QProgressBar { border: 1px solid #45475a; border-radius: 4px; text-align: center; color: #cdd6f4; }
QProgressBar::chunk { background-color: #89b4fa; border-radius: 3px; }
"""


class SuperClawApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setStyleSheet(DARK_STYLE)
        self.setApplicationName("SuperClaw")
        init_db()


def run_gui():
    """Launch the SuperClaw GUI application"""
    import sys
    from gui.main_window import MainWindow
    app = SuperClawApp(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
