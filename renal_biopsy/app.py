import sqlite3
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from . import config
from .db import Database
from .ui.login import LoginDialog
from .ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_TITLE)
    app.setStyle("Fusion")
    font = QFont("Microsoft JhengHei UI", 10)
    app.setFont(font)
    app.setQuitOnLastWindowClosed(False)

    state = {"db": None, "win": None}

    def show_login():
        while True:
            dlg = LoginDialog()
            if dlg.exec() != QDialog.Accepted:
                if state["db"]:
                    state["db"].close()
                app.quit()
                return
            path = config.get_db_path()
            try:
                if state["db"] is None or state["db"].path != path:
                    if state["db"]:
                        state["db"].close()
                    state["db"] = Database(path)
            except (sqlite3.Error, OSError) as e:
                state["db"] = None
                QMessageBox.critical(None, "無法開啟資料庫",
                                     f"無法開啟資料庫：\n{path}\n\n{e}\n\n"
                                     "請確認網路資料夾已連線，或按「變更資料庫位置」重新選擇。")
                continue
            try:
                state["db"].auto_backup()
            except Exception:
                pass  # 備份失敗不影響使用
            break
        win = MainWindow(state["db"], dlg.role)
        win.logged_out.connect(show_login)
        state["win"] = win
        win.show()

    def on_last_closed():
        # 使用者直接關閉主視窗（非登出）時結束程式
        win = state["win"]
        if win is not None and not win.isVisible() and not win._logging_out:
            if state["db"]:
                state["db"].close()
            app.quit()

    app.lastWindowClosed.connect(on_last_closed)
    show_login()
    return app.exec()
