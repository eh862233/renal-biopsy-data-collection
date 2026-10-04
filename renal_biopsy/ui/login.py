import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import config


class LoginDialog(QDialog):
    """登入畫面：選擇訪客或管理者。成功後 self.role 為 'guest' 或 'admin'。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.role = None
        self.setWindowTitle(config.APP_TITLE)
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        title = QLabel(config.APP_TITLE)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:22px;font-weight:bold;margin:12px;")
        root.addWidget(title)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # 第一頁：選擇身分
        choose = QWidget()
        v = QVBoxLayout(choose)
        self.btn_guest = QPushButton("訪客登入")
        self.btn_admin = QPushButton("管理者登入")
        for b in (self.btn_guest, self.btn_admin):
            b.setMinimumHeight(48)
            b.setStyleSheet("font-size:16px;")
            v.addWidget(b)
        hint = QLabel("訪客：查詢、新增與修改資料\n管理者：另可匯出 Excel、刪除紀錄")
        hint.setStyleSheet("color:gray;")
        hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)
        self.stack.addWidget(choose)

        # 第二頁：管理者帳密
        admin = QWidget()
        f = QFormLayout(admin)
        self.user = QLineEdit()
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        f.addRow("帳號", self.user)
        f.addRow("密碼", self.pwd)
        h = QHBoxLayout()
        back = QPushButton("返回")
        ok = QPushButton("登入")
        ok.setDefault(True)
        h.addWidget(back)
        h.addWidget(ok)
        f.addRow(h)
        self.stack.addWidget(admin)

        # 資料庫位置
        dbrow = QHBoxLayout()
        self.db_label = QLabel()
        self.db_label.setWordWrap(True)
        self.db_label.setStyleSheet("color:gray;font-size:11px;")
        change = QPushButton("變更資料庫位置…")
        dbrow.addWidget(self.db_label, 1)
        dbrow.addWidget(change)
        root.addLayout(dbrow)
        self._show_db()

        self.btn_guest.clicked.connect(self._guest)
        self.btn_admin.clicked.connect(lambda: (self.stack.setCurrentIndex(1), self.user.setFocus()))
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        ok.clicked.connect(self._admin)
        self.pwd.returnPressed.connect(self._admin)
        change.clicked.connect(self._change_db)

    def _show_db(self):
        self.db_label.setText(f"資料庫：{config.get_db_path()}")

    def _guest(self):
        self.role = "guest"
        self.accept()

    def _admin(self):
        if config.check_admin(self.user.text().strip(), self.pwd.text()):
            self.role = "admin"
            self.accept()
        else:
            QMessageBox.warning(self, "登入失敗", "帳號或密碼錯誤。")
            self.pwd.clear()
            self.pwd.setFocus()

    def _change_db(self):
        cur = config.get_db_path()
        path, _ = QFileDialog.getSaveFileName(
            self, "選擇或建立資料庫檔（可選共用網路資料夾中的 .db 檔）",
            cur, "SQLite database (*.db)", options=QFileDialog.DontConfirmOverwrite)
        if not path:
            return
        if not path.lower().endswith(".db"):
            path += ".db"
        if not os.path.exists(path):
            r = QMessageBox.question(self, "建立新資料庫",
                                     f"{path}\n\n此檔案不存在，要建立新的空白資料庫嗎？")
            if r != QMessageBox.Yes:
                return
        config.set_db_path(path)
        self._show_db()
