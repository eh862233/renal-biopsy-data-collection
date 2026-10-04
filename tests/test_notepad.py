"""醫院記事本匯入（測試資料為假資料，格式比照醫院系統產出的記事本）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from renal_biopsy.db import Database
from renal_biopsy.notepad_import import merge_into_record, parse_notepad, parse_notepad_text

NOTE = """1. Patient profile
Chart No.: 9900123
National ID: Not provided
Name: 測試病人
Birth date: Not provided (age 60 years old at admission)
Gender: Male
Admission date: 2025-03-01
Past history: Hypertension for 10 years
Operation history: None reported

2. Chief complaint
Leg edema and foamy urine for 2 weeks, elevated creatinine

3. Present illness
Edema since February. Renal biopsy performed on 2025-03-03.

4. Medication
Use of following medications:
- NSAID: None reported
- Chinese herb: Yes (unknown herbal tea)
- Contrast medium: Not reported
- Antibiotics: Cefazolin used before biopsy
Current medication list:
- Amlodipine 5 mg QD

5. Physical examination (latest at 2025-06-01)
Consciousness: Clear
Vital signs: BT 36.8, BP 150/90 mmHg, PR 88/min, RR 18/min
Body weight / Height / BMI: 72.5 kg / 170 cm / BMI not provided
HEENT: Not pale
Extremities: Pitting edema 2+

6. Lab data (closest to biopsy date 2025-03-03)

| Test | Result | Reference Range | Interpretation | Date |
|------|--------|-----------------|----------------|------|
| CBC | | | | |
| - WBC | 8.1 x10^3/uL | 4.5 - 11.0 | Normal | 2025-03-01 |
| - Hemoglobin | 11.2 g/dL | 12 - 16 | Low | 2025-03-01 |
| - Creatinine | 2.4 mg/dL | 0.7 - 1.3 | High | 2025-03-01 |
| - Total Cholesterol | >400 mg/dL | < 200 | High | 2025-03-02 |
| - IgG total | 300 - 350 mg/dL | 700 - 1600 | Low | 2025-03-02 - 2025-03-10 |
| - Triglyceride | 200-260 mg/dL | < 150 | High | 2025-03-02 |
| - Fibrinogen | 450 mg/dL | 200 - 400 | High | 2025-03-02 |
| - HBV markers | HBsAg Negative, Anti-HBc Reactive | | | 2025-03-02 |

7. Urine analysis

| Date | Urine Protein (dipstick) | Urine RBC (/HPF) | Urine Protein/Creatinine Ratio | 24-hr Urine Protein |
|------|---|---|---|---|
| 2025-02-20 | 2+ | 0-2 | 3.1 | - |
| 2025-03-02 | 4+ | 5-10 | 8.2 | 9000 mg/24hr |
| 2025-04-01 | 1+ | 0-2 | 1.0 | - |

8. Autoimmune profile (2025-03-02)

| Test | Result | Reference | Interpretation |
|------|--------|-----------|----------------|
| ANA | 1:160 speckled | Negative | Positive |
| Anti-dsDNA | <10 IU/mL | <10 | Negative |
| Anti-PLA2R | 85 RU/mL | <14 | Positive |
| Anti-CCP | Not reported | | |

9. Immunoglobulin profile

| Date | IgG (mg/dL) | C3 (mg/dL) | Kappa (mg/L) | κ/λ ratio |
|------|---|---|---|---|
| 2025-03-02 | 320 (low) | 95 (normal) | 20.1 | 1.2 |
| 2025-03-10 | 350 (low) | 90 | Not reported | Not reported |

10. Endocrine / infection profile

| Test | Result | Reference Range | Interpretation | Date |
|------|--------|-----------------|----------------|------|
| HbA1c | 6.1 % | 4 - 6 | High | 2025-03-02 |
| VDRL | Non-reactive | | Negative | 2025-03-02 |

11. Renal ultrasound
Findings: bilateral kidneys 10.5 cm, increased echogenicity

12. Renal biopsy
Date: 2025-03-03
Ultrasound findings: Not specified
Biopsy site: Right kidney
Number of cores obtained: 2 cores
Estimated number of glomeruli: 18 glomeruli
Cortex identified: Yes
Adequacy for LM / IF / EM: Adequate
Immediate post-biopsy complication: Small perirenal hematoma, observed

13. Pathology
Light microscopy (LM):
- Diffuse GBM thickening
Immunofluorescence (IF):
- IgG 3+ granular along capillary walls
Electron microscopy (EM): Subepithelial deposits
Diagnosis: Membranous nephropathy, PLA2R-associated
"""


def test_parse_profile_and_sections():
    r = parse_notepad_text(NOTE)
    assert r["patient"] == {"chart_no": "9900123", "name": "測試病人", "gender": "Male",
                            "past_history": "Hypertension for 10 years", "operation_history": "None"}
    d = r["data"]
    assert d["admission_date"] == "2025-03-01" and d["biopsy_date"] == "2025-03-03"
    assert set(d["cc_items"]) == {"Pitting edema", "Foamy urine", "Renal function deteriorated"}
    assert d["med_nsaid"] == "No" and d["med_chinese_herb"] == "Yes" and d["med_antibiotics"] == "Yes"
    assert "med_contrast" not in d
    assert "Amlodipine" in d["current_medication"]
    assert (d["pe_bt"], d["pe_sbp"], d["pe_dbp"], d["pe_pr"], d["pe_rr"]) == ("36.8", "150", "90", "88", "18")
    assert (d["pe_bw"], d["pe_height"]) == ("72.5", "170")
    assert d["pe_extremity"] == "Pitting edema 2+"
    assert d["bx_site"] == "Right kidney" and d["bx_cores"] == "2" and d["bx_glomeruli"] == "18"
    assert d["bx_cortex"] == "Yes"
    assert d["bx_adequacy_lm"] == d["bx_adequacy_if"] == d["bx_adequacy_em"] == "Adequate"
    assert d["bx_complication"] == "Perirenal hematoma"
    assert d["path_lm"] == "- Diffuse GBM thickening"
    assert d["path_em"] == "Subepithelial deposits"
    assert r["diagnosis_text"] == "Membranous nephropathy, PLA2R-associated"
    assert d["us_results"].startswith("Findings: bilateral kidneys")
    assert "bx_us_findings" not in d


def test_parse_labs_on_biopsy_date():
    r = parse_notepad_text(NOTE)
    labs = {l["panel"]: l["values"] for l in r["labs"]}
    assert all(l["lab_date"] == "2025-03-03" for l in r["labs"])
    assert labs["cbc"] == {"WBC": "8.1", "Hb": "11.2"}
    assert labs["chem"] == {"Cr": "2.4"}
    assert labs["liver"] == {"Chol": ">400"}
    # 範圍值的 IgG 由 Immunoglobulin 表（切片日前最近 2025-03-02）補上
    assert labs["ig"] == {"IgG": "320", "C3": "95", "Kappa": "20.1", "Kappa/Lambda": "1.2"}
    assert labs["endo"] == {"HBsAg": "Negative", "Anti-HBc": "Reactive", "HbA1c": "6.1",
                            "VDRL": "Non-reactive"}
    d = r["data"]
    assert d["ab_ana"] == "1:160 speckled" and d["ab_pla2r"] == "85 RU/mL" and "ab_ccp" not in d
    # 尿液表取切片日前最近的一列（2025-03-02）
    assert d["upcr"] == "8.2" and d["urine_24hr_protein"] == "9000" and d["ua_rbc"] == "Yes"
    assert d["urine_routine"].startswith("(2025-03-02)")

    w = "\n".join(r["warnings"])
    assert "Triglyceride" not in w and "TG：記事本為範圍值" in w
    assert "IgG：" not in w            # 已由其他段落補上，不再提醒
    assert "Fibrinogen" in w            # 沒有對應欄位
    assert "未提供生日（年齡 60 歲）" in w
    assert "Antibiotics" in w           # 非明確 Yes/No
    assert "理學檢查日期為 2025-06-01" in w
    assert "Spot UPCR" in w


def test_encodings(tmp_path):
    for enc in ("utf-8", "utf-8-sig", "cp950", "utf-16"):
        p = tmp_path / f"n_{enc}.txt"
        p.write_bytes(NOTE.replace("\n", "\r\n").encode(enc))
        assert parse_notepad(str(p))["patient"]["name"] == "測試病人"


def test_not_a_notepad():
    with pytest.raises(ValueError):
        parse_notepad_text("hello\nworld")


def test_merge_fill_only(tmp_path):
    db = Database(str(tmp_path / "m.db"))
    parsed = parse_notepad_text(NOTE)
    # 新紀錄：覆蓋表單預設值
    new = db.empty_record(None)
    merge_into_record(new, parsed, fill_only=False)
    assert new["biopsy"]["data"]["pe_consciousness"] == "Clear"
    assert new["biopsy"]["diagnosis_other"] == "Membranous nephropathy, PLA2R-associated"
    # 既有紀錄：只補空白
    rec = db.empty_record(None, chart_no="9900123")
    rec["biopsy"]["data"].update(biopsy_date="2025-03-03", pe_sbp="130")
    rec["biopsy"]["diagnoses"] = ["Membranous nephropathy"]
    rec["labs"] = [{"panel": "chem", "lab_date": "2025-03-03", "values": {"Cr": "2.0"}}]
    db.save_record(rec, "u")
    old = db.load_record(rec["biopsy"]["id"])
    merge_into_record(old, parsed, fill_only=True)
    d = old["biopsy"]["data"]
    assert d["pe_sbp"] == "130" and d["pe_dbp"] == "90"
    assert d["pe_consciousness"] == "clear"   # 預設值已存過，視為既有資料
    assert old["biopsy"]["diagnosis_other"] == ""
    chem = [l for l in old["labs"] if l["panel"] == "chem"][0]
    assert chem["values"] == {"Cr": "2.0"}
    assert old["patient"]["name"] == "測試病人"


# ---------------------------------------------------------------- 介面流程
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from renal_biopsy.ui.main_window import MainWindow
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    note = tmp_path / "note.txt"
    note.write_text(NOTE, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(note), "")))
    answers = {"value": QMessageBox.Yes}
    shown = []
    for name in ("question", "information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(
            lambda *a, _n=name, **k: shown.append((_n, a[2] if len(a) > 2 else "")) or answers["value"]))
    db = Database(str(tmp_path / "ui.db"))
    return MainWindow(db, "guest"), db, answers, shown


def test_import_new_patient(ui):
    w, db, _, shown = ui
    w.search.btn_notepad.click()
    f = w.form
    assert w.stack.currentWidget() is f and f.dirty
    assert f.widgets["chart_no"].text() == "9900123"
    assert f.widgets["pe_sbp"].text() == "150"
    assert "需要確認" in f.banner.text() and not f.banner_box.isHidden()
    w.save()
    assert ("information", "資料已儲存並上傳。") in shown
    p = db.find_patient("9900123")
    rec = db.load_record(db.list_biopsies(p["id"])[0]["id"])
    assert {l["lab_date"] for l in rec["labs"]} == {"2025-03-03"}


def test_import_into_existing_biopsy(ui):
    w, db, answers, shown = ui
    rec = db.empty_record(None, chart_no="9900123", name="測試病人")
    rec["biopsy"]["data"].update(biopsy_date="2025-03-03", pe_sbp="130")
    db.save_record(rec, "u")
    w.search.btn_notepad.click()
    assert w.form.record["biopsy"]["id"] == rec["biopsy"]["id"]  # 開啟同一天的既有紀錄
    assert w.form.widgets["pe_sbp"].text() == "130"
    assert w.form.widgets["pe_dbp"].text() == "90"
    assert "只補上原本空白的欄位" in w.form.banner.text()
    assert w.locked_id == rec["biopsy"]["id"]


def test_import_name_mismatch_cancel(ui):
    w, db, answers, shown = ui
    rec = db.empty_record(None, chart_no="9900123", name="別人")
    rec["biopsy"]["data"]["biopsy_date"] = "2024-01-01"
    db.save_record(rec, "u")
    answers["value"] = __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.No
    w.search.btn_notepad.click()
    assert shown[-1][0] == "question" and "姓名" in shown[-1][1]
    assert w.stack.currentWidget() is w.search
