import os
import sqlite3

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from .. import config
from ..db import ConflictError, DuplicateIdentifierError, patient_label
from ..notepad_import import merge_into_record, parse_notepad
from ..utils import (looks_like_name, looks_like_national_id, machine_user, normalize_national_id,
                     valid_national_id)
from .backup_dialog import RestoreDialog, backup_now
from .export_dialog import ExportDialog
from .import_dialog import import_tsn
from .record_form import RecordForm
from . import theme
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

        self.setWindowIcon(theme.app_icon())
        actions = []
        if self.is_admin:
            for text, slot in (("匯出 Excel", self.export),
                               ("立即備份", lambda: backup_now(self, self.db, self.user)),
                               ("從備份還原", self.restore),
                               ("匯入 TSN Excel", self.import_tsn)):
                act = QAction(text, self)
                act.triggered.connect(slot)
                actions.append(act)
        act_logout = QAction("登出", self)
        act_logout.triggered.connect(self.logout)
        self.statusBar().showMessage(f"資料庫：{db.path}")

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._build_header(actions, act_logout))
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.search = SearchPage(self.is_admin)
        self.form = RecordForm()
        self.stack.addWidget(self.search)
        self.stack.addWidget(self.form)

        self.search.search_requested.connect(self.do_search)
        self.search.patient_selected.connect(self.show_patient)
        self.search.notepad_requested.connect(self.import_notepad)
        self.search.open_requested.connect(self.open_biopsy)
        self.search.new_biopsy_requested.connect(self.new_biopsy)
        self.search.delete_requested.connect(self.delete_biopsy)
        self.form.save_requested.connect(self.save)
        self.form.back_requested.connect(self.back_to_search)

        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(60_000)
        self.heartbeat.timeout.connect(self._beat)
        self.search.edit.setFocus()

    def _build_header(self, actions, act_logout):
        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.setSpacing(12)
        h.addWidget(theme.logo_label(52))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(config.APP_TITLE)
        t.setStyleSheet("font-size:19px;font-weight:800;color:#ffffff;")
        st = QLabel("RENAL BIOPSY INTELLIGENCE REGISTRY · TSGH NEPHROLOGY")
        st.setStyleSheet(f"font-size:10px;letter-spacing:2px;color:{theme.CYAN};")
        titles.addWidget(t)
        titles.addWidget(st)
        h.addLayout(titles)
        h.addStretch()
        chip = QLabel(f"{'管理者' if self.is_admin else '訪客'} · {self.holder}")
        chip.setObjectName("ChipGold" if self.is_admin else "Chip")
        h.addWidget(chip, 0, Qt.AlignVCenter)
        h.addSpacing(8)
        for act in actions + [act_logout]:
            b = QToolButton()
            b.setDefaultAction(act)
            b.setCursor(Qt.PointingHandCursor)
            h.addWidget(b)
        return header

    # ------------------------------------------------------------------ 查詢
    def do_search(self, term: str):
        try:
            patients = self.db.search_patients(term)
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        if len(patients) == 1:
            self.show_patient(patients[0]["id"], term)
            return
        if len(patients) > 1:
            self.search.show_matches(term, patients)
            return
        self.search.show_result(term, None, [])
        if looks_like_national_id(term):
            kind, ids = "身分證字號", {"national_id": normalize_national_id(term)}
        elif looks_like_name(term):
            kind, ids = "姓名", {"name": term}
        else:
            kind, ids = "病歷號", {"chart_no": term}
        extra = ("請在 Patient profile 頁填寫病歷號或身分證字號（至少一個）。" if kind == "姓名" else
                 f"另一個號碼可在 Patient profile 頁補上；若{kind}判斷錯誤，也可在該頁修改。")
        r = QMessageBox.question(
            self, "查無資料",
            f"「{term}」目前沒有資料。\n要以此{kind}建立一位新病人嗎？\n\n（{extra}）")
        if r == QMessageBox.Yes:
            self._open_new(self.db.empty_record(None, **ids))

    def show_patient(self, patient_id: int, term: str = None):
        try:
            p = self.db.get_patient(patient_id)
            biopsies = self.db.list_biopsies(patient_id) if p else []
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        keep = term is None  # 從多位病人清單中選取時保留清單
        self.search.show_result(term if term is not None else self.search.term, p, biopsies,
                                keep_matches=keep)

    def _refresh_search(self, patient_id=None):
        """重新整理查詢頁（例如存檔、刪除後）。"""
        try:
            p = self.db.get_patient(patient_id) if patient_id else None
            if p:
                term = p.get("chart_no") or p.get("national_id")
                self.search.edit.setText(term)
                self.search.show_result(term, p, self.db.list_biopsies(p["id"]))
            else:
                self.search.show_result(self.search.term or None, None, [])
        except sqlite3.Error:
            pass

    def new_biopsy(self):
        if not self.search.patient:
            return
        try:
            p = self.db.get_patient(self.search.patient["id"])
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        if p is None:
            QMessageBox.warning(self, "找不到", "此病人資料已被刪除。")
            self._refresh_search()
            return
        self._open_new(self.db.empty_record(p))

    # ------------------------------------------------------------------ 醫院記事本
    def import_notepad(self):
        cfg = config.load_config()
        path, _ = QFileDialog.getOpenFileName(self, "選擇醫院系統產出的記事本",
                                              cfg.get("last_notepad_dir", ""),
                                              "記事本 (*.txt);;所有檔案 (*)")
        if not path:
            return
        cfg["last_notepad_dir"] = os.path.dirname(path)
        config.save_config(cfg)
        try:
            parsed = parse_notepad(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "無法讀取記事本", str(e))
            return
        pi = parsed["patient"]
        try:
            by_id = self.db.find_patient(pi["national_id"]) if pi.get("national_id") else None
            by_chart = self.db.find_patient(pi["chart_no"]) if pi.get("chart_no") else None
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        if by_id and by_chart and by_id["id"] != by_chart["id"]:
            QMessageBox.warning(
                self, "無法匯入",
                f"記事本的病歷號屬於「{patient_label(by_chart)}」，身分證字號卻屬於"
                f"「{patient_label(by_id)}」，請先確認資料。")
            return
        patient = by_id or by_chart
        if not patient and not pi.get("chart_no") and not pi.get("national_id"):
            QMessageBox.information(self, "記事本沒有號碼",
                                    "記事本中找不到病歷號或身分證字號，將建立新病人，"
                                    "請在 Patient profile 頁補上號碼。")
        if patient and pi.get("name") and patient.get("name") and pi["name"] != patient["name"]:
            r = QMessageBox.question(
                self, "姓名不一致",
                f"記事本的姓名「{pi['name']}」與系統中此病人的姓名「{patient['name']}」不同。\n"
                "確定是同一位病人並繼續匯入嗎？")
            if r != QMessageBox.Yes:
                return

        bdate = parsed["data"].get("biopsy_date")
        existing = None
        try:
            if patient and bdate:
                existing = next((b for b in self.db.list_biopsies(patient["id"])
                                 if b["biopsy_date"] == bdate), None)
            if existing:
                ok, who = self.db.acquire_lock(existing["id"], self.holder)
                if not ok:
                    QMessageBox.warning(self, "無法匯入",
                                        f"此病人 {bdate} 的切片紀錄正由「{who}」編輯中，請稍後再匯入。")
                    return
                self._set_lock(existing["id"])
                rec = self.db.load_record(existing["id"])
            else:
                rec = self.db.empty_record(patient)
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return
        n = merge_into_record(rec, parsed, fill_only=bool(existing))

        where = (f"已有 {bdate} 的切片紀錄，只補上原本空白的欄位" if existing else
                 "既有病人的新切片紀錄" if patient else "新病人")
        lines = [f"已從記事本「{os.path.basename(path)}」帶入 {n} 個欄位（{where}），尚未儲存。",
                 "請逐頁檢查內容，並到 Pathology 頁勾選病理診斷後，按「儲存並上傳」。"]
        if parsed["warnings"]:
            lines.append("需要確認：")
            lines += [f"• {w}" for w in parsed["warnings"]]
        self.form.load(rec, banner="\n".join(lines))
        self.form.dirty = True
        self.stack.setCurrentWidget(self.form)

    def _open_new(self, rec):
        self.form.load(rec)
        self.stack.setCurrentWidget(self.form)

    def open_biopsy(self, biopsy_id: int):
        try:
            ok, who = self.db.acquire_lock(biopsy_id, self.holder)
            rec = self.db.load_record(biopsy_id)
        except KeyError:
            QMessageBox.warning(self, "找不到", "此筆紀錄已被刪除。")
            self._refresh_search(self.search.patient and self.search.patient["id"])
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
        b, p = rec["biopsy"], rec["patient"]
        nid = p.get("national_id")
        if nid and nid != rec.get("patient_orig", {}).get("national_id") \
                and not valid_national_id(nid):
            r = QMessageBox.question(
                self, "身分證字號可能有誤",
                f"身分證字號「{nid}」的格式或檢查碼不正確。\n確定要以此號碼儲存嗎？")
            if r != QMessageBox.Yes:
                return
        try:
            if b.get("id") is None and p.get("id"):
                same = [x for x in self.db.list_biopsies(p["id"])
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
        except ValueError as e:  # 號碼重複、未填號碼
            QMessageBox.warning(self, "尚未儲存", str(e))
            return
        except ConflictError as e:
            r = QMessageBox.warning(
                self, "資料衝突，尚未儲存",
                f"{e}\n\n按「Yes」重新載入最新資料（您這次的修改將會遺失）；\n"
                "按「No」留在此畫面（可先把需要的內容複製起來）。",
                QMessageBox.Yes | QMessageBox.No)
            if r == QMessageBox.Yes and b.get("id") is not None:
                self.open_biopsy(b["id"])
            elif r == QMessageBox.Yes:
                self.stack.setCurrentWidget(self.search)
                self.do_search(p.get("national_id") or p.get("chart_no"))
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
        pid = self.form.record.get("patient", {}).get("id")
        self.stack.setCurrentWidget(self.search)
        if pid:
            self._refresh_search(pid)

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
        self._refresh_search(self.search.patient and self.search.patient["id"])

    def export(self):
        ExportDialog(self.db, self.user, self).exec()

    def _prepare_bulk_change(self, what: str) -> bool:
        """還原、匯入前：離開編輯畫面，並確認沒有其他電腦正在編輯。"""
        if self.stack.currentWidget() is self.form:
            if not self._confirm_leave():
                return False
            self._release_lock()
            self.stack.setCurrentWidget(self.search)
        try:
            others = self.db.active_locks(self.holder)
        except sqlite3.Error as e:
            QMessageBox.critical(self, "資料庫錯誤", DB_ERROR_MSG.format(e))
            return False
        if others:
            QMessageBox.warning(self, f"暫時無法{what}",
                                f"以下電腦正在編輯資料，請等對方關閉紀錄後再{what}：\n\n"
                                + "\n".join(others))
            return False
        return True

    def import_tsn(self):
        if self.is_admin and self._prepare_bulk_change("匯入"):
            if import_tsn(self, self.db, self.user):
                self._refresh_search(self.search.patient and self.search.patient["id"])

    def restore(self):
        if not self.is_admin or not self._prepare_bulk_change("還原"):
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
