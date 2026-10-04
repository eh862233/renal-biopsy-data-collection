import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import config
from . import theme


class LoginDialog(QDialog):
    """登入畫面：選擇訪客或管理者。成功後 self.role 為 'guest' 或 'admin'。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.role = None
        self.setWindowTitle(config.APP_TITLE)
        self.setWindowIcon(theme.app_icon())
        self.resize(980, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.bg = theme.NeuralBackground()
        outer.addWidget(self.bg)
        root = QHBoxLayout(self.bg)
        root.setContentsMargins(56, 40, 56, 40)
        root.setSpacing(48)

        # ---- 左側：科徽與標題 ----
        brand = QVBoxLayout()
        brand.setSpacing(10)
        brand.addStretch()
        logo = theme.logo_label(250)
        brand.addWidget(logo, 0, Qt.AlignHCenter)
        brand.addSpacing(14)
        title = QLabel(config.APP_TITLE)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:28px;font-weight:800;color:#ffffff;letter-spacing:2px;")
        brand.addWidget(title)
        sub = QLabel("RENAL BIOPSY INTELLIGENCE REGISTRY")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"font-size:12px;letter-spacing:4px;color:{theme.CYAN};")
        brand.addWidget(sub)
        dept = QLabel("TSGH · Division of Nephrology")
        dept.setAlignment(Qt.AlignCenter)
        dept.setStyleSheet(f"font-size:12px;color:{theme.GOLD};")
        brand.addWidget(dept)
        brand.addStretch()
        root.addLayout(brand, 3)

        # ---- 右側：登入卡片 ----
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(380)
        theme.glow(card, theme.BLUE, radius=60, alpha=90)
        c = QVBoxLayout(card)
        c.setContentsMargins(30, 30, 30, 24)
        c.setSpacing(14)
        welcome = QLabel("歡迎使用")
        welcome.setObjectName("H1")
        c.addWidget(welcome)
        self.prompt = QLabel("請選擇登入身分")
        self.prompt.setObjectName("Muted")
        c.addWidget(self.prompt)
        c.addSpacing(6)

        self.stack = QStackedWidget()
        c.addWidget(self.stack)

        choose = QWidget()
        v = QVBoxLayout(choose)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.btn_guest = QPushButton("訪客登入")
        self.btn_guest.setObjectName("Primary")
        self.btn_admin = QPushButton("管理者登入")
        for b in (self.btn_guest, self.btn_admin):
            b.setMinimumHeight(52)
            b.setStyleSheet(b.styleSheet() + "font-size:16px;border-radius:12px;")
            b.setCursor(Qt.PointingHandCursor)
            v.addWidget(b)
        hint = QLabel("訪客：查詢、新增與修改資料\n管理者：另可匯出、匯入、備份、還原、刪除")
        hint.setObjectName("Muted")
        hint.setStyleSheet("font-size:12px;")
        v.addWidget(hint)
        v.addStretch()
        self.stack.addWidget(choose)

        admin = QWidget()
        f = QVBoxLayout(admin)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(10)
        self.user = QLineEdit()
        self.user.setPlaceholderText("帳號")
        self.pwd = QLineEdit()
        self.pwd.setPlaceholderText("密碼")
        self.pwd.setEchoMode(QLineEdit.Password)
        for w in (self.user, self.pwd):
            w.setMinimumHeight(42)
            f.addWidget(w)
        h = QHBoxLayout()
        back = QPushButton("返回")
        ok = QPushButton("登入")
        ok.setObjectName("Primary")
        ok.setDefault(True)
        for b in (back, ok):
            b.setMinimumHeight(42)
            b.setCursor(Qt.PointingHandCursor)
        h.addWidget(back, 1)
        h.addWidget(ok, 2)
        f.addLayout(h)
        f.addStretch()
        self.stack.addWidget(admin)

        c.addStretch()
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{theme.BORDER};")
        c.addWidget(line)
        self.db_label = QLabel()
        self.db_label.setWordWrap(True)
        self.db_label.setObjectName("Muted")
        self.db_label.setStyleSheet("font-size:11px;")
        c.addWidget(self.db_label)
        change = QPushButton("變更資料庫位置…")
        change.setStyleSheet("font-size:12px;padding:4px 10px;")
        c.addWidget(change, 0, Qt.AlignRight)
        self._show_db()

        right = QVBoxLayout()
        right.addStretch()
        right.addWidget(card)
        right.addStretch()
        root.addLayout(right, 2)

        self.btn_guest.clicked.connect(self._guest)
        self.btn_admin.clicked.connect(self._show_admin)
        back.clicked.connect(self._show_choose)
        ok.clicked.connect(self._admin)
        self.pwd.returnPressed.connect(self._admin)
        change.clicked.connect(self._change_db)

    def _show_admin(self):
        self.stack.setCurrentIndex(1)
        self.prompt.setText("管理者登入")
        self.user.setFocus()

    def _show_choose(self):
        self.stack.setCurrentIndex(0)
        self.prompt.setText("請選擇登入身分")

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
