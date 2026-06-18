"""SuperClaw Application Entry Point"""
import sys
import os

if getattr(sys, 'frozen', False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, base_dir)

import models
from models.database import init_db
from utils.logger import setup_logger

logger = setup_logger()


def main():
    logger.info("Initializing SuperClaw...")
    init_db()
    logger.info("Database initialized.")

    if "--gui" in sys.argv:
        from PySide6.QtWidgets import QApplication
        from gui.app import DARK_STYLE
        from gui.login_dialog import LoginDialog
        from gui.main_window import MainWindow
        from services.user_service import UserService

        app = QApplication(sys.argv)
        app.setStyleSheet(DARK_STYLE)
        app.setApplicationName("SuperClaw")

        user_service = UserService()
        user_service.init_admin()

        # Login loop: supports logout -> re-login
        while True:
            login = LoginDialog()
            if login.exec() != 1:
                break

            user = login.logged_in_user
            logger.info(f"User '{user.username}' logged in (role={user.role})")

            window = MainWindow(current_user=user)
            window.logout_signal.connect(lambda: None)
            window.show()
            app.exec()

            logger.info(f"User '{user.username}' logged out")
            window = None

        sys.exit(0)
    elif "--cli" in sys.argv:
        logger.info("CLI mode not yet implemented")
    else:
        logger.info("SuperClaw ready. Use --gui for desktop mode.")


if __name__ == "__main__":
    main()
