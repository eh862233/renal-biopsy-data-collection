"""管理者：立即備份、從備份還原。"""
import os
import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .. import config
from ..db import inspect_backup


def backup_now(parent, db, user: str):
    cfg = config.load_config()
    folder = cfg.get("last_backup_dir") or os.path.expanduser("~")
    name = f"renal_biopsy_backup_{datetime.now():%Y%m%d_%H%M}.db"
    path, _ = QFileDialog.getSaveFileName(parent, "選擇備份位置（例如隨身碟）",
                                          os.path.join(folder, name), "Database backup (*.db)")
    if not path:
        return
    if not path.lower().endswith(".db"):
        path += ".db"
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        info = db.backup_to(path, user)
    except (ValueError, OSError, sqlite3.Error) as e:
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(parent, "備份失敗", f"備份失敗：\n{e}")
        return
    QApplication.restoreOverrideCursor()
    cfg["last_backup_dir"] = os.path.dirname(path)
    config.save_config(cfg)
    QMessageBox.information(
        parent, "備份完成",
        f"已備份到：\n{path}\n\n內容：{info['patients']} 位病人、{info['biopsies']} 筆切片紀錄\n\n"
        "建議把備份放在共用資料夾以外的地方（隨身碟、自己的電腦），並妥善保管：備份檔含有病人資料。")


def _fmt_size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{max(n // 1024, 1)} KB"


class RestoreDialog(QDialog):
    """列出備份檔，選擇後還原。self.selected 為選定的備份檔路徑。"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.selected = None
        self.setWindowTitle("從備份還原")
        self.resize(760, 480)
        root = QVBoxLayout(self)
        msg = QLabel("選擇要還原的備份。還原後，資料庫會回到該備份當時的狀態；"
                     "備份之後新增或修改的資料會被取代。\n"
                     "還原前程式會自動把目前的資料另存一份（before_restore_…），選錯還可以再還原回來。")
        msg.setWordWrap(True)
        root.addWidget(msg)

        root.addWidget(QLabel(f"備份資料夾：{db.backup_folder()}"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["備份檔", "建立時間", "大小"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_info)
        self.table.doubleClicked.connect(self._restore)
        root.addWidget(self.table, 1)

        self.info = QLabel("")
        self.info.setStyleSheet("font-weight:bold;")
        root.addWidget(self.info)

        h = QHBoxLayout()
        other = QPushButton("選擇其他位置的備份檔…")
        other.clicked.connect(self._browse)
        h.addWidget(other)
        h.addStretch()
        self.btn_restore = QPushButton("還原")
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self._restore)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        h.addWidget(self.btn_restore)
        h.addWidget(cancel)
        root.addLayout(h)
        self._load_list()

    def _load_list(self):
        folder = self.db.backup_folder()
        files = []
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if f.endswith(".db") and os.path.isfile(p):
                    files.append((os.path.getmtime(p), p))
        for mtime, p in sorted(files, reverse=True):
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(os.path.basename(p))
            it.setData(Qt.UserRole, p)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(
                datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(r, 2, QTableWidgetItem(_fmt_size(os.path.getsize(p))))
        if not files:
            self.info.setText("備份資料夾中沒有備份檔，請按「選擇其他位置的備份檔…」。")

    def _current(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def _describe(self, path):
        try:
            i = inspect_backup(path)
        except ValueError as e:
            return None, str(e)
        return i, (f"此備份：{i['patients']} 位病人、{i['biopsies']} 筆切片紀錄"
                   f"（最後修改 {i['last_updated'] or '—'}）")

    def _show_info(self):
        p = self._current()
        if not p:
            return
        ok, text = self._describe(p)
        self.info.setText(text)
        self.btn_restore.setEnabled(ok is not None)

    def _browse(self):
        start = config.load_config().get("last_backup_dir") or self.db.backup_folder()
        path, _ = QFileDialog.getOpenFileName(self, "選擇備份檔", start, "Database backup (*.db)")
        if path:
            self._confirm(path)

    def _restore(self, *_):
        p = self._current()
        if p:
            self._confirm(p)

    def _confirm(self, path):
        info, text = self._describe(path)
        if info is None:
            QMessageBox.warning(self, "無法使用此檔案", text)
            return
        try:
            cur = inspect_backup(self.db.path)
            now = f"目前資料：{cur['patients']} 位病人、{cur['biopsies']} 筆切片紀錄\n"
        except ValueError:
            now = ""
        r = QMessageBox.warning(
            self, "確認還原",
            f"確定要用這個備份取代目前的資料嗎？\n\n{path}\n\n{text}\n{now}\n"
            "目前的資料會先自動另存一份，之後仍可還原回來。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            self.selected = path
            self.accept()
