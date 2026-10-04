"""管理者匯出 Excel 對話框。"""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSpinBox, QVBoxLayout)

from .. import schema
from ..export import export_records


class ExportDialog(QDialog):
    def __init__(self, db, user: str, parent=None):
        super().__init__(parent)
        self.db = db
        self.user = user
        self.setWindowTitle("匯出 Excel")
        self.resize(720, 680)
        root = QVBoxLayout(self)

        cond = QGroupBox("篩選條件（未勾選／留空 = 不限）")
        f = QFormLayout(cond)

        this_year = date.today().year
        yr = QHBoxLayout()
        self.year_on = QCheckBox("限定切片年份")
        self.year_from = QSpinBox()
        self.year_to = QSpinBox()
        for s in (self.year_from, self.year_to):
            s.setRange(1980, 2100)
            s.setValue(this_year)
        yr.addWidget(self.year_on)
        yr.addWidget(self.year_from)
        yr.addWidget(QLabel("～"))
        yr.addWidget(self.year_to)
        yr.addStretch()
        f.addRow("切片年份", yr)

        gh = QHBoxLayout()
        self.g_male = QCheckBox("Male")
        self.g_female = QCheckBox("Female")
        gh.addWidget(self.g_male)
        gh.addWidget(self.g_female)
        gh.addStretch()
        f.addRow("性別", gh)

        ah = QHBoxLayout()
        self.age_on = QCheckBox("限定年齡")
        self.age_min = QSpinBox()
        self.age_max = QSpinBox()
        self.age_min.setRange(0, 120)
        self.age_max.setRange(0, 120)
        self.age_max.setValue(120)
        ah.addWidget(self.age_on)
        ah.addWidget(self.age_min)
        ah.addWidget(QLabel("～"))
        ah.addWidget(self.age_max)
        ah.addWidget(QLabel("歲（切片時）"))
        ah.addStretch()
        f.addRow("年齡", ah)

        self.dx_list = QListWidget()
        self.dx_list.setMinimumHeight(170)
        for dx in schema.DIAGNOSES:
            it = QListWidgetItem(dx)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.dx_list.addItem(it)
        f.addRow("病理診斷\n（符合任一）", self.dx_list)

        self.charts = QLineEdit()
        self.charts.setPlaceholderText("病歷號或身分證字號，多個以逗號或空白分隔")
        f.addRow("病歷號／身分證", self.charts)
        root.addWidget(cond)

        secs = QGroupBox("匯出欄位（病歷號、身分證字號、姓名、性別、年齡、切片日期、診斷一律包含）")
        g = QGridLayout(secs)
        self.sec_boxes = {}
        for i, s in enumerate(schema.SECTIONS):
            cb = QCheckBox(s.title)
            cb.setChecked(True)
            self.sec_boxes[s.key] = cb
            g.addWidget(cb, i // 3, i % 3)
        root.addWidget(secs)

        self.preview = QLabel()
        root.addWidget(self.preview)
        bb = QDialogButtonBox()
        self.btn_count = QPushButton("預覽筆數")
        self.btn_export = QPushButton("匯出…")
        self.btn_export.setObjectName("Primary")
        bb.addButton(self.btn_count, QDialogButtonBox.ActionRole)
        bb.addButton(self.btn_export, QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Close).setText("關閉")
        bb.rejected.connect(self.reject)
        self.btn_count.clicked.connect(self._count)
        self.btn_export.clicked.connect(self._export)
        root.addWidget(bb)

    def _filters(self):
        kw, crit = {}, {}
        if self.year_on.isChecked():
            a, b = sorted((self.year_from.value(), self.year_to.value()))
            kw.update(year_from=a, year_to=b)
            crit["切片年份"] = f"{a} ～ {b}"
        genders = [g for g, cb in (("Male", self.g_male), ("Female", self.g_female)) if cb.isChecked()]
        if genders:
            kw["genders"] = genders
            crit["性別"] = ", ".join(genders)
        if self.age_on.isChecked():
            a, b = sorted((self.age_min.value(), self.age_max.value()))
            kw.update(age_min=a, age_max=b)
            crit["年齡"] = f"{a} ～ {b}"
        dx = [self.dx_list.item(i).text() for i in range(self.dx_list.count())
              if self.dx_list.item(i).checkState() == Qt.Checked]
        if dx:
            kw["diagnoses"] = dx
            crit["病理診斷"] = "; ".join(dx)
        charts = [c for c in self.charts.text().replace(",", " ").split() if c]
        if charts:
            kw["chart_nos"] = charts
            crit["病歷號／身分證"] = ", ".join(charts)
        crit["匯出者"] = self.user
        return kw, crit

    def _query(self):
        kw, crit = self._filters()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            return self.db.query_records(**kw), crit
        finally:
            QApplication.restoreOverrideCursor()

    def _count(self):
        try:
            recs, _ = self._query()
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"查詢失敗：{e}")
            return
        pts = len({r["patient"]["id"] for r in recs})
        self.preview.setText(f"符合條件：{len(recs)} 筆切片紀錄（{pts} 位病人）")

    def _export(self):
        sections = [k for k, cb in self.sec_boxes.items() if cb.isChecked()]
        try:
            recs, crit = self._query()
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"查詢失敗：{e}")
            return
        if not recs:
            QMessageBox.information(self, "匯出", "沒有符合條件的資料。")
            return
        name = f"renal_biopsy_export_{date.today():%Y%m%d}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "儲存 Excel", name, "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_records(recs, path, crit, sections)
        except PermissionError:
            QMessageBox.critical(self, "錯誤", "無法寫入檔案，請確認該檔案沒有在 Excel 中開啟。")
            return
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"匯出失敗：{e}")
            return
        self.preview.setText(f"已匯出 {len(recs)} 筆 → {path}")
        QMessageBox.information(self, "匯出完成", f"已匯出 {len(recs)} 筆資料至：\n{path}")
