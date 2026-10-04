"""GUI 煙霧測試（無螢幕環境以 offscreen 執行）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from renal_biopsy.db import Database
from renal_biopsy.ui.login import LoginDialog
from renal_biopsy.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def no_dialogs(monkeypatch):
    shown = []
    for name in ("question", "information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name,
                            staticmethod(lambda *a, _n=name, **k: shown.append((_n, a[2] if len(a) > 2 else "")) or QMessageBox.Yes))
    return shown


def test_login(app, no_dialogs):
    d = LoginDialog()
    d.btn_guest.click()
    assert d.role == "guest"
    d = LoginDialog()
    d.user.setText("neph88099")
    d.pwd.setText("wrong")
    d._admin()
    assert d.role is None
    d.pwd.setText("neph88099")
    d._admin()
    assert d.role == "admin"


def test_create_edit_flow(app, no_dialogs, tmp_path):
    db = Database(str(tmp_path / "g.db"))
    w = MainWindow(db, "guest")
    assert not w.search.btn_del.isVisible()
    w.do_search("B123")  # 查無資料 → 自動建立新紀錄
    assert w.stack.currentWidget() is w.form
    f = w.form
    f.widgets["birth_date"].setText("1980/2/3")
    f.widgets["gender"].setCurrentText("Female")
    f.widgets["pe_bw"].setText("60")
    f.widgets["pe_height"].setText("160")
    assert f.widgets["pe_bmi"].text() == "23.4"

    # 未填切片日期 → 不能儲存
    w.save()
    assert db.find_patient("B123") is None
    assert "必填" in no_dialogs[-1][1]

    f.widgets["biopsy_date"].setText("2024-05-06")
    f.lab_tables["chem"].add_row("2024/05/05", {"Cr": "1.8"})
    f.dx_group.boxes["Membranous nephropathy"].setChecked(True)
    f.widgets["path_lm"].setPlainText("thickened GBM")
    w.save()
    assert ("information", "資料已儲存並上傳。") in no_dialogs
    assert f.widgets["age"].text() == "44"
    bid = f.record["biopsy"]["id"]
    rec = db.load_record(bid)
    assert rec["patient"]["birth_date"] == "1980-02-03"
    assert rec["labs"][0]["lab_date"] == "2024-05-05"
    assert w.locked_id == bid

    # 另一台電腦開啟同一筆 → 唯讀
    db2 = Database(db.path)
    w2 = MainWindow(db2, "admin")
    w2.holder = "other@PC2"
    w2.open_biopsy(bid)
    assert w2.form.read_only and not w2.form.btn_save.isEnabled()

    # 修改後再存
    f.widgets["path_if"].setPlainText("IgG 3+")
    w.save()
    assert db.load_record(bid)["biopsy"]["version"] == 2
    w.back_to_search()
    assert w.locked_id is None
    assert w.search.table.rowCount() == 1


def test_backup_and_restore_ui(app, no_dialogs, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from renal_biopsy.ui import backup_dialog
    from renal_biopsy.ui.backup_dialog import RestoreDialog

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    db = Database(str(tmp_path / "share" / "r.db"))
    guest = MainWindow(db, "guest")
    names = [a.text() for a in guest.findChildren(type(guest.menuBar().addAction("x")))]
    assert "立即備份" not in names and "從備份還原" not in names

    w = MainWindow(db, "admin")
    w.do_search("C1")
    w.form.widgets["biopsy_date"].setText("2024-01-01")
    w.save()
    w.back_to_search()

    # 立即備份到「隨身碟」
    usb = tmp_path / "usb" / "bk.db"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(usb), "")))
    backup_dialog.backup_now(w, db, w.user)
    assert usb.exists()
    assert no_dialogs[-1][0] == "information"

    # 新增資料後還原
    w.do_search("C2")
    w.form.widgets["biopsy_date"].setText("2024-02-02")
    w.save()
    assert w.stack.currentWidget() is w.form  # 正在編輯 → 還原時會先回到查詢頁
    monkeypatch.setattr(RestoreDialog, "exec", lambda self: (setattr(self, "selected", str(usb)),
                                                             RestoreDialog.Accepted)[1])
    w.restore()
    assert db.find_patient("C2") is None and db.find_patient("C1") is not None
    assert w.stack.currentWidget() is w.search

    # 其他電腦正在編輯 → 拒絕還原
    bid = db.list_biopsies(db.find_patient("C1")["id"])[0]["id"]
    db.acquire_lock(bid, "someone@PC9")
    w.restore()
    assert "someone@PC9" in no_dialogs[-1][1]

    # 對話框能列出備份資料夾中的檔案（含還原前自動備份）
    dlg = RestoreDialog(db)
    assert dlg.table.rowCount() >= 1
    dlg.table.selectRow(0)
    assert "位病人" in dlg.info.text()


def test_search_by_national_id(app, no_dialogs, tmp_path):
    db = Database(str(tmp_path / "n.db"))
    w = MainWindow(db, "guest")
    w.do_search("a123456789")  # 查無資料 → 以身分證字號建立新病人
    f = w.form
    assert f.widgets["national_id"].text() == "A123456789"
    assert f.widgets["chart_no"].text() == ""
    f.widgets["name"].setText("測試甲")
    f.widgets["biopsy_date"].setText("2024-05-06")
    w.save()
    assert ("information", "資料已儲存並上傳。") in no_dialogs
    w.back_to_search()
    assert "測試甲" in w.search.info.text() and w.search.table.rowCount() == 1

    # 兩個號碼都清空 → 不能存
    w.open_biopsy(db.list_biopsies(db.find_patient("A123456789")["id"])[0]["id"])
    f.widgets["national_id"].setText("")
    w.save()
    assert "至少要填一個" in no_dialogs[-1][1]

    # 補上病歷號後，用病歷號也查得到；新增第二次切片
    f.widgets["national_id"].setText("A123456789")
    f.widgets["chart_no"].setText("5566")
    w.save()
    w.back_to_search()
    w.do_search("5566")
    assert w.search.patient["national_id"] == "A123456789"
    w.search.btn_new.click()
    assert w.form.record["patient"]["id"] == w.search.patient["id"]
