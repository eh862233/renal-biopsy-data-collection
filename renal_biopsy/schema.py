"""資料欄位定義（依 Renal biopsy data 投影片）。

表單畫面與 Excel 匯出都依照這份定義自動產生，
日後要新增/修改欄位，只要改這個檔案即可。
"""
from dataclasses import dataclass, field
from typing import List, Optional

# 欄位型態
TEXT = "text"            # 單行文字
MULTILINE = "multiline"  # 多行文字
NUMBER = "number"        # 數值（以文字儲存，匯出時轉數字）
DATE = "date"            # 日期 YYYY-MM-DD
CHOICE = "choice"        # 下拉選單（單選）
CHECKS = "checks"        # 多選勾選
COMPUTED = "computed"    # 自動計算，不可編輯


@dataclass
class Field:
    key: str
    label: str
    type: str = TEXT
    options: List[str] = field(default_factory=list)
    default: str = ""
    unit: str = ""
    hint: str = ""


@dataclass
class Section:
    key: str
    title: str
    fields: List[Field] = field(default_factory=list)
    lab_panels: List[str] = field(default_factory=list)  # 對應 LAB_PANELS 的 key
    images: bool = False
    diagnosis: bool = False


GENDERS = ["Male", "Female"]
NEG_POS = ["", "No", "Yes"]

# ---- 病人層級欄位（同一病歷號碼共用） ----
PATIENT_FIELDS = [
    Field("birth_date", "Birth date", DATE),
    Field("gender", "Gender", CHOICE, [""] + GENDERS),
    Field("past_history", "Past history", MULTILINE),
    Field("operation_history", "Operation history", MULTILINE),
]

# ---- 病理診斷選單（可複選 + 其他） ----
DIAGNOSES = [
    "IgA nephropathy",
    "IgA vasculitis nephritis (HSP)",
    "Membranous nephropathy",
    "Minimal change disease",
    "FSGS",
    "Lupus nephritis class I",
    "Lupus nephritis class II",
    "Lupus nephritis class III",
    "Lupus nephritis class IV",
    "Lupus nephritis class V",
    "Lupus nephritis class VI",
    "Diabetic nephropathy",
    "Hypertensive nephrosclerosis",
    "ANCA-associated GN",
    "Anti-GBM disease",
    "MPGN",
    "C3 glomerulopathy",
    "Infection-related GN",
    "Thrombotic microangiopathy",
    "Amyloidosis",
    "Monoclonal gammopathy-related (MIDD / cast nephropathy)",
    "Fibrillary GN",
    "Acute interstitial nephritis",
    "Acute tubular injury / necrosis",
    "Chronic tubulointerstitial nephritis",
    "Alport syndrome / Thin basement membrane",
    "Advanced chronic sclerosing nephropathy",
]

# ---- 抽血檢查（每個 panel 可輸入多個日期） ----
LAB_PANELS = {
    "cbc": ("CBC / Coagulation",
            ["WBC", "Hb", "HCT", "MCV", "PLT", "INR", "PT", "APTT",
             "SEG", "LYM", "MONO", "EOS", "BASO"]),
    "chem": ("Renal function / Electrolytes",
             ["BUN", "Cr", "eGFR", "Na", "K", "Cl", "Ca", "Mg", "IP"]),
    "liver": ("Liver / Lipid",
              ["AST", "ALT", "LDH", "TP", "Alb", "Chol", "HDL", "LDL", "TG", "UA"]),
    "ig": ("Immunoglobulin / Complement",
           ["IgG", "IgA", "IgM", "IgE", "IgD", "C3", "C4", "Kappa", "Lambda", "Kappa/Lambda"]),
    "endo": ("Endocrine / Infection",
             ["FBS", "HbA1c", "fT4", "TSH", "HIV", "HBsAg", "Anti-HBc", "Anti-HCV", "VDRL", "CRP"]),
}


def _autoab(key, label, ref=""):
    return Field(key, label, TEXT, hint=ref)


SECTIONS: List[Section] = [
    Section("profile", "Patient profile", [
        Field("admission_date", "Admission date", DATE),
        Field("age", "Age (切片時)", COMPUTED, hint="依生日與切片日期自動計算"),
    ]),
    Section("chief_complaint", "Chief complaint", [
        Field("cc_items", "Chief complaint", CHECKS,
              ["Renal function deteriorated", "Pitting edema", "Foamy urine",
               "Hematuria", "Proteinuria"]),
        Field("cc_other", "Other / description", MULTILINE),
    ]),
    Section("present_illness", "Present illness", [
        Field("present_illness", "Present illness", MULTILINE),
    ]),
    Section("medication", "Medication", [
        Field("med_nsaid", "NSAID", CHOICE, NEG_POS),
        Field("med_chinese_herb", "Chinese herb", CHOICE, NEG_POS),
        Field("med_contrast", "Contrast medium", CHOICE, NEG_POS),
        Field("med_antibiotics", "Antibiotics", CHOICE, NEG_POS),
        Field("med_diuretics", "Diuretic agents", CHOICE, NEG_POS),
        Field("med_vaccination", "Vaccination within 1 year", CHOICE, NEG_POS),
        Field("current_medication", "Current medication", MULTILINE),
    ]),
    Section("pe", "Physical examination", [
        Field("pe_consciousness", "Consciousness", TEXT, default="clear"),
        Field("pe_bt", "BT", NUMBER, unit="°C"),
        Field("pe_pr", "PR", NUMBER, unit="/min"),
        Field("pe_rr", "RR", NUMBER, unit="/min"),
        Field("pe_sbp", "SBP", NUMBER, unit="mmHg"),
        Field("pe_dbp", "DBP", NUMBER, unit="mmHg"),
        Field("pe_bw", "Body weight", NUMBER, unit="kg"),
        Field("pe_height", "Height", NUMBER, unit="cm"),
        Field("pe_bmi", "BMI", COMPUTED, unit="kg/m²", hint="依體重身高自動計算"),
        Field("pe_heent", "HEENT", TEXT, default="pink conjunctiva, no icteric sclera"),
        Field("pe_neck", "Neck", TEXT, default="no lymphadenopathy, no jugular engorgement"),
        Field("pe_chest", "Chest", TEXT, default="clear breathing sounds"),
        Field("pe_heart", "Heart", TEXT, default="regular heart beats without heart murmurs"),
        Field("pe_abdomen", "Abdomen", MULTILINE,
              default="no Murphy's sign, no abdominal tenderness, no rebound pain, "
                      "no shifting dullness, no C-P angle knocking pain"),
        Field("pe_extremity", "Extremity", TEXT, default="no pitting edema"),
    ]),
    Section("lab", "Lab data", lab_panels=["cbc", "chem", "liver"]),
    Section("urine", "Urine analysis", [
        Field("urine_routine", "Urine routine", MULTILINE),
        Field("uacr", "Spot UACR", NUMBER, unit="mg/g"),
        Field("upcr", "Spot UPCR", NUMBER, unit="mg/g"),
        Field("urine_24hr_protein", "24hr urine protein", NUMBER, unit="mg/day"),
        Field("urine_longitudinal", "Longitudinal results", MULTILINE),
    ]),
    Section("autoimmune", "Autoimmune profile", [
        _autoab("ab_dsdna", "Anti-dsDNA", "Neg <10 / Equ 10-15 / Pos >15 IU/mL"),
        _autoab("ab_ana", "ANA"),
        _autoab("ab_rf", "Rheumatoid factor", "Pos ≥14 IU/mL"),
        _autoab("ab_ro", "Anti-Ro", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
        _autoab("ab_la", "Anti-La", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
        _autoab("ab_canca", "C-ANCA", "Neg <2 / Equ 2-3 / Pos >3 IU/mL"),
        _autoab("ab_panca", "P-ANCA", "Neg <3.5 / Equ 3.5-5 / Pos >5 IU/mL"),
        _autoab("ab_gbm", "Anti-GBM", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
        _autoab("ab_cryo", "Cryoglobulin"),
        _autoab("ab_asma", "ASMA"),
        _autoab("ab_rnp", "RNP (optional)", "Neg <5 / Equ 5-10 / Pos >10 U/mL"),
        _autoab("ab_sm", "SM (optional)", "Neg <5 / Equ 5-10 / Pos >10 U/mL"),
        _autoab("ab_scl70", "SCL-70 (optional)", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
        _autoab("ab_ribop", "Ribosomal-P (optional)", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
        _autoab("ab_jo1", "JO-1 (optional)", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
        _autoab("ab_ccp", "Anti-CCP (optional)", "Neg <7 / Equ 7-10 / Pos >10 U/mL"),
    ]),
    Section("immunoglobulin", "Immunoglobulin profile", [
        Field("ife", "Immunofixation electrophoresis (IFE)", MULTILINE),
        Field("electrophoresis", "Electrophoresis", MULTILINE),
    ], lab_panels=["ig"]),
    Section("endocrine", "Endocrine / infection profile", lab_panels=["endo"]),
    Section("ultrasound", "Renal ultrasound", [
        Field("us_results", "Results", MULTILINE),
    ], images=True),
    Section("biopsy", "Renal biopsy", [
        Field("biopsy_date", "Biopsy date（必填）", DATE),
        Field("bx_us_findings", "Ultrasound findings", MULTILINE),
        Field("bx_site", "Biopsy site", CHOICE, ["", "Right kidney", "Left kidney"]),
        Field("bx_cores", "Number of cores obtained", NUMBER),
        Field("bx_glomeruli", "Estimated number of glomeruli", NUMBER),
        Field("bx_cortex", "Cortex identified", CHOICE, ["", "Yes", "No"]),
        Field("bx_adequacy_lm", "Adequacy for LM", CHOICE, ["", "Adequate", "Inadequate"]),
        Field("bx_adequacy_if", "Adequacy for IF", CHOICE, ["", "Adequate", "Inadequate"]),
        Field("bx_adequacy_em", "Adequacy for EM", CHOICE, ["", "Adequate", "Inadequate"]),
        Field("bx_complication", "Immediate post-biopsy complication", CHOICE,
              ["", "None", "Gross hematuria", "Perirenal hematoma",
               "Blood transfusion required", "Other"]),
        Field("bx_complication_other", "Complication (other)", TEXT),
    ]),
    Section("pathology", "Pathology", [
        Field("path_lm", "LM", MULTILINE),
        Field("path_if", "IF", MULTILINE),
        Field("path_em", "EM", MULTILINE),
    ], diagnosis=True),
]


def all_biopsy_fields() -> List[Field]:
    return [f for s in SECTIONS for f in s.fields]


def find_field(key: str) -> Optional[Field]:
    for f in all_biopsy_fields() + PATIENT_FIELDS:
        if f.key == key:
            return f
    return None
