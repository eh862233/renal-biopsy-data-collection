"""管理者：匯入 TSN 腎臟疾病登錄系統匯出的 Excel。"""
import os
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QLabel,
                               QMessageBox, QPlainTextEdit, QVBoxLayout)

from .. import config
from ..tsn_import import parse_tsn


class ImportPreviewDialog(QDialog):
    def __init__(self, path, stats, n_items, skipped, warnings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("匯入 TSN Excel — 確認")
        self.resize(720, 520)
        root = QVBoxLayout(self)
        summary = QLabel(
            f"<b>{os.path.basename(path)}</b><br><br>"
            f"可匯入 {n_items} 列：<br>"
            f"　・新病人 {stats['patients_new']} 位；既有病人補齊空白資料 {stats['patients_updated']} 位<br>"
            f"　・新切片紀錄 {stats['biopsies_new']} 筆<br>"
            f"　・已存在的切片紀錄補齊空白欄位 {stats['biopsies_updated']} 筆、"
            f"資料相同不需變動 {stats['unchanged']} 筆<br>"
            f"略過 {len(skipped)} 列；需核對 {len(warnings)} 項<br><br>"
            "已存在的資料<b>不會被覆蓋</b>，只會補上原本空白的欄位。"
            "匯入前會自動另存一份目前的資料（before_import_…），可用「從備份還原」復原。")
        summary.setWordWrap(True)
        root.addWidget(summary)
        if skipped or warnings:
            box = QPlainTextEdit()
            box.setReadOnly(True)
            lines = []
            if skipped:
                lines += ["【略過的列】"] + skipped + [""]
            if warnings:
                lines += ["【需要核對】"] + warnings
            box.setPlainText("\n".join(lines))
            root.addWidget(box, 1)
        bb = QDialogButtonBox()
        bb.addButton("開始匯入", QDialogButtonBox.AcceptRole)
        bb.addButton("取消", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)


def import_tsn(parent, db, user: str) -> bool:
    """回傳是否有匯入資料。"""
    cfg = config.load_config()
    path, _ = QFileDialog.getOpenFileName(parent, "選擇 TSN 匯出的 Excel 檔",
                                          cfg.get("last_import_dir", ""), "Excel (*.xlsx)")
    if not path:
        return False
    cfg["last_import_dir"] = os.path.dirname(path)
    config.save_config(cfg)

    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        items, skipped, warnings = parse_tsn(path)
        stats = db.import_items(items, user, dry_run=True)
    except PermissionError:
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(parent, "無法讀取", "無法讀取檔案，請先在 Excel 中關閉該檔案。")
        return False
    except (ValueError, OSError, sqlite3.Error) as e:
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(parent, "無法匯入", f"無法讀取此檔案：\n{e}")
        return False
    except Exception as e:  # 非預期的檔案格式
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(parent, "無法匯入", f"檔案格式不符：\n{e}")
        return False
    QApplication.restoreOverrideCursor()

    if not items:
        QMessageBox.information(parent, "匯入", "檔案中沒有可匯入的資料。\n\n" + "\n".join(skipped[:20]))
        return False
    dlg = ImportPreviewDialog(path, stats, len(items), skipped, warnings, parent)
    if dlg.exec() != QDialog.Accepted:
        return False

    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        safety = db.safety_copy("before_import")
        stats = db.import_items(items, user)
    except (ValueError, OSError, sqlite3.Error) as e:
        QApplication.restoreOverrideCursor()
        QMessageBox.critical(parent, "匯入失敗", f"匯入失敗，資料沒有變動：\n{e}")
        return False
    QApplication.restoreOverrideCursor()
    QMessageBox.information(
        parent, "匯入完成",
        f"新病人 {stats['patients_new']} 位、新切片紀錄 {stats['biopsies_new']} 筆、"
        f"補齊既有紀錄 {stats['biopsies_updated']} 筆。\n\n"
        f"匯入前的資料已另存為：\n{safety}"
        + (f"\n\n以下 {len(warnings)} 項需要核對：\n" + "\n".join(warnings[:15])
           + ("\n…" if len(warnings) > 15 else "") if warnings else ""))
    return True
