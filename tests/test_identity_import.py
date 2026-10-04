"""病人識別（病歷號／身分證字號）、舊資料庫升級、TSN Excel 匯入。

測試用的 TSN 檔案為程式產生的假資料。
"""
import sqlite3
from datetime import datetime

import pytest
from openpyxl import Workbook

from renal_biopsy.db import Database, DuplicateIdentifierError
from renal_biopsy.tsn_import import parse_tsn
from renal_biopsy.utils import looks_like_national_id, valid_national_id


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    yield d
    d.close()


def new_rec(db, date="2024-01-01", **ids):
    rec = db.empty_record(None, **ids)
    rec["biopsy"]["data"]["biopsy_date"] = date
    return rec


def test_national_id_helpers():
    assert valid_national_id("A123456789") and valid_national_id("a123456789")
    assert not valid_national_id("A123456788")
    assert looks_like_national_id("a123456789") and not looks_like_national_id("12345678")


def test_identify_by_either_number(db):
    db.save_record(new_rec(db, national_id="a123456789", name="測試甲"), "u")
    p = db.find_patient("A123456789")
    assert p["national_id"] == "A123456789" and p["chart_no"] is None
    assert db.find_patient("a123456789")["id"] == p["id"]  # 不分大小寫

    # 之後補上病歷號，兩種號碼都查得到
    rec = db.load_record(db.list_biopsies(p["id"])[0]["id"])
    rec["patient"]["chart_no"] = "778899"
    db.save_record(rec, "u")
    assert db.find_patient("778899")["id"] == p["id"]

    # 新增第二次切片仍屬同一人
    rec2 = db.empty_record(db.find_patient("778899"))
    rec2["biopsy"]["data"]["biopsy_date"] = "2025-01-01"
    db.save_record(rec2, "u")
    assert len(db.list_biopsies(p["id"])) == 2


def test_identifier_rules(db):
    with pytest.raises(ValueError):
        db.save_record(new_rec(db), "u")  # 沒有任何號碼
    db.save_record(new_rec(db, chart_no="111"), "u")
    db.save_record(new_rec(db, national_id="A123456789"), "u")
    # 把別人的身分證字號填到另一位病人 → 拒絕
    rec = db.load_record(db.list_biopsies(db.find_patient("111")["id"])[0]["id"])
    rec["patient"]["national_id"] = "A123456789"
    with pytest.raises(DuplicateIdentifierError):
        db.save_record(rec, "u")
    # 多位病人都沒有病歷號不算重複
    db.save_record(new_rec(db, national_id="B123456780"), "u")


OLD_SCHEMA = """
CREATE TABLE patients (chart_no TEXT PRIMARY KEY, birth_date TEXT DEFAULT '', gender TEXT DEFAULT '',
    past_history TEXT DEFAULT '', operation_history TEXT DEFAULT '', created_at TEXT, created_by TEXT,
    updated_at TEXT, updated_by TEXT, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE biopsies (id INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_no TEXT NOT NULL REFERENCES patients(chart_no) ON DELETE CASCADE,
    biopsy_date TEXT DEFAULT '', admission_date TEXT DEFAULT '', diagnoses TEXT DEFAULT '[]',
    diagnosis_other TEXT DEFAULT '', data TEXT DEFAULT '{}', created_at TEXT, created_by TEXT,
    updated_at TEXT, updated_by TEXT, version INTEGER NOT NULL DEFAULT 1);
CREATE INDEX idx_biopsies_chart ON biopsies(chart_no);
CREATE TABLE labs (id INTEGER PRIMARY KEY AUTOINCREMENT,
    biopsy_id INTEGER NOT NULL REFERENCES biopsies(id) ON DELETE CASCADE,
    panel TEXT NOT NULL, lab_date TEXT DEFAULT '', "values" TEXT DEFAULT '{}');
CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT,
    biopsy_id INTEGER NOT NULL REFERENCES biopsies(id) ON DELETE CASCADE,
    filename TEXT DEFAULT '', data BLOB, created_at TEXT);
INSERT INTO patients(chart_no, gender, birth_date) VALUES ('C100', 'Male', '1970-01-01');
INSERT INTO biopsies(id, chart_no, biopsy_date, diagnoses, data)
    VALUES (7, 'C100', '2024-02-02', '["IgA nephropathy"]', '{"path_lm": "old"}');
INSERT INTO labs(biopsy_id, panel, lab_date, "values") VALUES (7, 'chem', '2024-02-02', '{"Cr": "1.1"}');
INSERT INTO images(biopsy_id, filename, data) VALUES (7, 'us.png', x'89504E47');
"""


def test_migrate_old_database(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.close()

    d = Database(str(path))
    p = d.find_patient("C100")
    assert p["gender"] == "Male" and p["national_id"] is None
    rec = d.load_record(7)
    assert rec["biopsy"]["data"]["path_lm"] == "old"
    assert rec["labs"][0]["values"]["Cr"] == "1.1"
    assert rec["images"][0]["data"] == b"\x89PNG"
    assert d.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # 升級後可正常存檔、刪除（連帶刪除檢驗與圖片）
    rec["patient"]["national_id"] = "A123456789"
    d.save_record(rec, "u")
    assert d.find_patient("A123456789")["id"] == p["id"]
    d.delete_biopsy(7, "admin")
    assert d.conn.execute("SELECT COUNT(*) FROM labs").fetchone()[0] == 0
    assert d.conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
    d.close()
    Database(str(path)).close()  # 再開一次不會重複升級


# ---------------------------------------------------------------- TSN 匯入
HEADERS = ["序號", "系統病患ID", "狀態", "姓名", "身分證字號", "性別", "生日", "年齡(系統顯示)",
           "切片時年齡", "登錄類別", "醫院名稱", "DM", "HTN", "發病原因", "家族史", "危險因子",
           "用藥習慣", "切片編號", "切片日期", "切片年份", "Clinical diagnosis",
           "Clinical diagnosis (Others 說明)", "Pathology diagnosis",
           "Pathology diagnosis (Others 說明)", "檢驗編號", "檢驗數據上傳日期", "上傳年份",
           "Creatinine", "Blood UN", "Cr/eGFR (系統計算)", "24hr urine protein", "Spot UPCR",
           "U/A RBC", "Hemoglobin", "ANA", "C3", "FLC ratio", "HBsAg", "PEP serum"]


def make_tsn(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "全部病患"
    ws.append(["基本資料"] + [None] * (len(HEADERS) - 1))
    ws.append(HEADERS)
    for r in rows:
        ws.append([r.get(h) for h in HEADERS])
    ws.append([None] * len(HEADERS))  # 空白列
    wb.save(path)


def tsn_row(**kw):
    row = {"序號": 1, "系統病患ID": 960, "姓名": "測試甲", "身分證字號": "A123456789", "性別": "男",
           "生日": datetime(1970, 5, 1), "切片時年齡": '=IF(G3="","",1)', "登錄類別": "TSN",
           "DM": "Yes", "HTN": "No", "切片編號": 828, "切片日期": datetime(2024, 1, 4),
           "Clinical diagnosis": "Acute kidney injury; Persistent hematuria",
           "Pathology diagnosis": "Membranous glomerulonephritis; Others",
           "Pathology diagnosis (Others 說明)": "IgG4-related kidney disease",
           "檢驗數據上傳日期": datetime(2024, 11, 7), "Creatinine": 2.2, "Blood UN": 71,
           "24hr urine protein": 19424, "Spot UPCR": 1.5, "U/A RBC": "Yes", "Hemoglobin": 12.9,
           "ANA": "Negative", "C3": 178.9, "FLC ratio": 1.7, "HBsAg": "Negative",
           "PEP serum": "no M-spike"}
    row.update(kw)
    return row


def test_parse_tsn(tmp_path):
    path = tmp_path / "tsn.xlsx"
    make_tsn(path, [
        tsn_row(),
        tsn_row(序號=2, 姓名="測試乙", 身分證字號="B123456780", 性別="女", 切片日期=None),
        tsn_row(序號=3, 姓名="測試丙", 身分證字號=None),
        tsn_row(序號=4, 姓名="測試丁", 身分證字號="C123456781", Creatinine=14, **{"Blood UN": 0.9,
                "Pathology diagnosis": "Crescentic glomerulonephritis type 3; Lupus nephritis",
                "Spot UPCR": "N/A"}),
    ])
    items, skipped, warnings = parse_tsn(str(path))
    assert len(items) == 2 and len(skipped) == 2
    a = items[0]
    assert a["patient"] == {"national_id": "A123456789", "chart_no": "", "name": "測試甲",
                            "gender": "Male", "birth_date": "1970-05-01"}
    assert a["biopsy_date"] == "2024-01-04"
    assert a["diagnoses"] == ["Membranous nephropathy"]
    assert a["diagnosis_other"] == "IgG4-related kidney disease"
    assert a["data"]["clinical_dx"] == ["Acute kidney injury", "Persistent hematuria"]
    assert a["data"]["tsn_lab_upload_date"] == "2024-11-07"
    assert a["data"]["urine_24hr_protein"] == "19424" and a["data"]["upcr"] == "1.5"
    assert a["data"]["electrophoresis"] == "no M-spike" and a["data"]["hx_dm"] == "Yes"
    assert a["labs"]["chem"] == {"Cr": "2.2", "BUN": "71"}
    assert a["labs"]["ig"] == {"C3": "178.9", "Kappa/Lambda": "1.7"}
    d = items[1]
    assert d["diagnoses"] == ["Crescentic GN type 3 (pauci-immune)",
                              "Lupus nephritis (class not specified)"]
    assert "upcr" not in d["data"]
    assert any("可能欄位對調" in w for w in warnings)
    assert any("Spot UPCR" in w for w in warnings)


def test_import_merge(db, tmp_path):
    path = tmp_path / "tsn.xlsx"
    make_tsn(path, [tsn_row(), tsn_row(序號=2, 姓名="測試乙", 身分證字號="B123456780",
                                        性別="女", 切片日期=datetime(2025, 3, 3))])
    items, _, _ = parse_tsn(str(path))

    # 已有一位病人（有病歷號、身分證）且同一天的切片已手動輸入部分資料
    rec = new_rec(db, "2024-01-04", chart_no="555", national_id="A123456789")
    rec["biopsy"]["data"]["hx_dm"] = "No"  # 手動輸入過，不可被覆蓋
    rec["labs"] = [{"panel": "chem", "lab_date": "2024-01-04", "values": {"Cr": "2.0"}}]
    db.save_record(rec, "u")

    preview = db.import_items(items, "admin", dry_run=True)
    assert preview == {"patients_new": 1, "patients_updated": 1, "biopsies_new": 1,
                       "biopsies_updated": 1, "unchanged": 0}
    assert db.find_patient("B123456780") is None  # 預覽不寫入

    stats = db.import_items(items, "admin")
    assert stats == preview
    p = db.find_patient("555")
    assert p["name"] == "測試甲" and p["birth_date"] == "1970-05-01"
    m = db.load_record(db.list_biopsies(p["id"])[0]["id"])
    assert m["biopsy"]["data"]["hx_dm"] == "No"           # 保留手動資料
    assert m["biopsy"]["data"]["tsn_biopsy_no"] == "828"  # 補上空白欄位
    assert m["biopsy"]["diagnoses"] == ["Membranous nephropathy"]
    chem = [l for l in m["labs"] if l["panel"] == "chem"][0]
    assert chem["values"] == {"Cr": "2.0", "BUN": "71"}   # Cr 不覆蓋，BUN 補上
    assert len(db.list_biopsies(p["id"])) == 1

    n = db.load_record(db.list_biopsies(db.find_patient("B123456780")["id"])[0]["id"])
    assert n["patient"]["gender"] == "Female"
    assert {l["lab_date"] for l in n["labs"]} == {"2025-03-03"}  # 檢驗記在切片日

    # 再匯入一次：沒有變動
    again = db.import_items(items, "admin")
    assert again["unchanged"] == 2 and again["biopsies_new"] == 0
