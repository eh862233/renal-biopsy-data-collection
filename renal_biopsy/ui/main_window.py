import sqlite3

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from .. import config
from ..db import ConflictError
from ..utils import machine_user
from .backup_dialog import RestoreDialog, backup_now
from .export_dialog import ExportDialog
from .record_form import RecordForm
from .search_page import SearchPage

DB_ERROR_MSG = ("無法存取資料庫（可能是網路資料夾中斷，或其他電腦正在寫入）。\n"
                "請稍後再試一次；若持續發生請確認網路連線。\n\n詳細：{}")


class MainWindow(QMainWindow):
    logged_out = Signal()

    def __init__(self, db, role: str):
        super().__init__()
        self.db = db
        self.role = role
        self.is_admin = role == "admin"
        self.holder = machine_user()
        self.user = f"{config.ADMIN_USERNAME if self.is_admin else 'guest'} ({self.holder})"
        self.locked_id = None
        self._logging_out = False

        self.setWindowTitle(f"{config.APP_TITLE} — {'管理者' if self.is_admin else '訪客'}")
        self.resize(1200, 820)

        tb = self.addToolBar("main")
        tb.setMovable(False)
        if self.is_admin:
            act_export = QAction("匯出 Excel", self)
            act_export.triggered.connect(self.export)
            tb.addAction(act_export)
            act_backup = QAction("立即備份", self)
            act_backup.triggered.connect(lambda: backup_now(self, self.db, self.user))
            tb.addAction(act_backup)
            act_restore = QAction("從備份還原", self)
            act_restore.triggered.connect(self.restore)
            tb.addAction(act_restore)
            tb.addSeparator()
        act_logout = QAction("登出", self)
        act_logout.triggered.connect(self.logout)
        tb.addAction(act_logout)
        self.statusBar().showMessage(f"登入身分：{'管理者' if self.is_admin else '訪客'}　"
                                     f"資料庫：{db.path}")

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.search = SearchPage(self.is_admin)
        self.form = RecordForm()
        self.stack.addWidget(self.search)
        self.stack.addWidget(self.form)

        self.search.search_requested.connect(self.do_search)
        self.search.open_requested.connect(self.open_biopsy)
        self.search.new_biopsy_requested.connect(self.new_biopsy)
        self.search.delete_requested.connect(self.delete_biopsy)
        self.form.save_requested.connect(self.save)
        self.form.back_requested.connect(self.back_to_search)

        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(60_000)
        self.heartbeat.timeout.connect(self._beat)
        self.search.edit.setFocus()

    # ------------------------------------------------------------------ 查詢
    def do_search(self, chart_no: str):
        try:
            patient = self.db.get_patient(chart_no)
            biopsies = self.db.list_biopsies(chart_no) if patient else []
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        self.search.show_result(chart_no, patient, biopsies)
        if not patient:
            r = QMessageBox.question(self, "查無資料",
                                     f"病歷號「{chart_no}」目前沒有資料。\n要建立一筆新的病歷資料嗎？")
            if r == QMessageBox.Yes:
                self.new_biopsy(chart_no)

    def new_biopsy(self, chart_no: str):
        try:
            rec = self.db.empty_record(chart_no)
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        self.form.load(rec)
        self.stack.setCurrentWidget(self.form)

    def open_biopsy(self, biopsy_id: int):
        try:
            ok, who = self.db.acquire_lock(biopsy_id, self.holder)
            rec = self.db.load_record(biopsy_id)
        except KeyError:
            QMessageBox.warning(self, "找不到", "此筆紀錄已被刪除。")
            self.do_search(self.search.chart_no)
            return
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        if ok:
            self._set_lock(biopsy_id)
            self.form.load(rec)
        else:
            self.form.load(rec, read_only=True,
                           banner=f"此筆紀錄目前正由「{who}」編輯中，您只能檢視（唯讀）。"
                                  "待對方關閉後再重新開啟即可修改。")
        self.stack.setCurrentWidget(self.form)

    # ------------------------------------------------------------------ 儲存
    def save(self):
        try:
            rec = self.form.collect()
        except ValueError as e:
            QMessageBox.warning(self, "資料有誤，尚未儲存", str(e))
            return
        b = rec["biopsy"]
        try:
            if b.get("id") is None:
                same = [x for x in self.db.list_biopsies(rec["patient"]["chart_no"])
                        if x["biopsy_date"] == b["data"].get("biopsy_date")]
                if same:
                    r = QMessageBox.question(
                        self, "可能重複",
                        f"此病人已有一筆切片日期為 {b['data']['biopsy_date']} 的紀錄。\n"
                        "確定要再新增一筆嗎？（若是要修改原紀錄，請按 No 後返回查詢開啟該筆）")
                    if r != QMessageBox.Yes:
                        return
            bid = self.db.save_record(rec, self.user)
            if self.locked_id != bid:
                ok, _ = self.db.acquire_lock(bid, self.holder)
                if ok:
                    self._set_lock(bid)
            fresh = self.db.load_record(bid)
        except ConflictError as e:
            r = QMessageBox.warning(
                self, "資料衝突，尚未儲存",
                f"{e}\n\n按「Yes」重新載入最新資料（您這次的修改將會遺失）；\n"
                "按「No」留在此畫面（可先把需要的內容複製起來）。",
                QMessageBox.Yes | QMessageBox.No)
            if r == QMessageBox.Yes and b.get("id") is not None:
                self.open_biopsy(b["id"])
            elif r == QMessageBox.Yes:
                self.do_search(rec["patient"]["chart_no"])
                self.stack.setCurrentWidget(self.search)
            return
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤，尚未儲存", DB_ERROR_MSG.format(e))
            return
        self.form.load(fresh, keep_page=self.form.nav.currentRow())
        self.statusBar().showMessage(f"已儲存並上傳（{fresh['biopsy']['updated_at']}）", 8000)
        QMessageBox.information(self, "完成", "資料已儲存並上傳。")

    # ------------------------------------------------------------------ 返回 / 刪除
    def _confirm_leave(self) -> bool:
        if not self.form.dirty or self.form.read_only:
            return True
        r = QMessageBox.question(self, "尚未儲存",
                                 "資料有修改尚未儲存，要先儲存嗎？",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            self.save()
            return not self.form.dirty
        return True

    def back_to_search(self):
        if not self._confirm_leave():
            return
        self._release_lock()
        chart = self.form.record.get("patient", {}).get("chart_no")
        self.stack.setCurrentWidget(self.search)
        if chart:
            self.search.edit.setText(chart)
            try:
                p = self.db.get_patient(chart)
                self.search.show_result(chart, p, self.db.list_biopsies(chart) if p else [])
            except sqlite3.Error:
                pass

    def delete_biopsy(self, biopsy_id: int):
        if not self.is_admin:
            return
        r = QMessageBox.warning(self, "確認刪除", "確定要永久刪除這筆切片紀錄嗎？此動作無法復原。",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        try:
            ok, who = self.db.acquire_lock(biopsy_id, self.holder)
            if not ok:
                QMessageBox.warning(self, "無法刪除", f"此筆紀錄正由「{who}」編輯中。")
                return
            self.db.delete_biopsy(biopsy_id, self.user)
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        self.do_search(self.search.chart_no) if self.db.get_patient(self.search.chart_no) \
            else self.search.show_result(self.search.chart_no, None, [])

    def export(self):
        ExportDialog(self.db, self.user, self).exec()

    def restore(self):
        if not self.is_admin:
            return
        if self.stack.currentWidget() is self.form:
            if not self._confirm_leave():
                return
            self._release_lock()
            self.stack.setCurrentWidget(self.search)
        try:
            others = self.db.active_locks(self.holder)
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        if others:
            QMessageBox.warning(self, "暫時無法還原",
                                "以下電腦正在編輯資料，請等對方關閉紀錄後再還原：\n\n"
                                + "\n".join(others))
            return
        dlg = RestoreDialog(self.db, self)
        if dlg.exec() != RestoreDialog.Accepted or not dlg.selected:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            safety = self.db.restore_from(dlg.selected, self.user)
        except (ValueError, OSError, sqlite3.Error) as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "還原失敗", f"還原失敗，資料沒有變動：\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.search.edit.clear()
        self.search.show_result(None, None, [])
        QMessageBox.information(
            self, "還原完成",
            f"已從備份還原：\n{dlg.selected}\n\n還原前的資料已另存為：\n{safety}\n"
            "（若選錯，可再用「從備份還原」選這個檔案還原回來）")

    # ------------------------------------------------------------------ 鎖
    def _set_lock(self, biopsy_id):
        self._release_lock()
        self.locked_id = biopsy_id
        self.heartbeat.start()

    def _release_lock(self):
        if self.locked_id is not None:
            try:
                self.db.release_lock(self.locked_id, self.holder)
            except sqlite3.Error:
                pass
        self.locked_id = None
        self.heartbeat.stop()

    def _beat(self):
        if self.locked_id is not None:
            try:
                self.db.refresh_lock(self.locked_id, self.holder)
            except sqlite3.Error:
                pass

    # ------------------------------------------------------------------ 登出 / 關閉
    def logout(self):
        if self.stack.currentWidget() is self.form and not self._confirm_leave():
            return
        self._logging_out = True
        self.close()

    def closeEvent(self, event):
        if not self._logging_out and self.stack.currentWidget() is self.form \
                and not self._confirm_leave():
            event.ignore()
            return
        self._release_lock()
        event.accept()
        if self._logging_out:
            self.logged_out.emit()
