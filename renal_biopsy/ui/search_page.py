from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


class SearchPage(QWidget):
    search_requested = Signal(str)
    open_requested = Signal(int)
    new_biopsy_requested = Signal(str)
    delete_requested = Signal(int)

    def __init__(self, is_admin: bool, parent=None):
        super().__init__(parent)
        self.chart_no = ""
        root = QVBoxLayout(self)
        title = QLabel("輸入病歷號碼查詢")
        title.setStyleSheet("font-size:18px;font-weight:bold;")
        root.addWidget(title)
        h = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("病歷號碼 (Chart No.)")
        self.edit.setStyleSheet("font-size:16px;padding:4px;")
        btn = QPushButton("查詢")
        btn.setMinimumWidth(90)
        h.addWidget(self.edit, 1)
        h.addWidget(btn)
        root.addLayout(h)
        btn.clicked.connect(self._search)
        self.edit.returnPressed.connect(self._search)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("font-size:14px;margin-top:10px;")
        root.addWidget(self.info)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["切片日期", "病理診斷", "最後修改時間", "修改者"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._open)
        root.addWidget(self.table, 1)

        bh = QHBoxLayout()
        self.btn_open = QPushButton("開啟／修改選取的紀錄")
        self.btn_new = QPushButton("＋ 新增一次切片紀錄")
        self.btn_del = QPushButton("刪除選取的紀錄")
        self.btn_del.setVisible(is_admin)
        self.btn_open.clicked.connect(self._open)
        self.btn_new.clicked.connect(lambda: self.new_biopsy_requested.emit(self.chart_no))
        self.btn_del.clicked.connect(self._delete)
        bh.addWidget(self.btn_open)
        bh.addWidget(self.btn_new)
        bh.addStretch()
        bh.addWidget(self.btn_del)
        root.addLayout(bh)
        self.show_result(None, None, [])

    def _search(self):
        cn = self.edit.text().strip()
        if cn:
            self.search_requested.emit(cn)

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _open(self, *_):
        bid = self._selected_id()
        if bid is not None:
            self.open_requested.emit(bid)

    def _delete(self):
        bid = self._selected_id()
        if bid is not None:
            self.delete_requested.emit(bid)

    def show_result(self, chart_no, patient, biopsies):
        self.chart_no = chart_no or ""
        self.table.setRowCount(0)
        has = bool(patient)
        for w in (self.table, self.btn_open, self.btn_new, self.btn_del):
            w.setEnabled(has)
        if chart_no is None:
            self.info.setText("")
            return
        if not has:
            self.info.setText(f"病歷號 <b>{chart_no}</b> 查無資料。")
            return
        self.info.setText(
            f"病歷號 <b>{chart_no}</b>　性別：{patient.get('gender') or '—'}　"
            f"生日：{patient.get('birth_date') or '—'}　共 {len(biopsies)} 次切片紀錄"
            "（雙擊可開啟）")
        for b in biopsies:
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(b["biopsy_date"] or "（未填）")
            it.setData(Qt.UserRole, b["id"])
            self.table.setItem(r, 0, it)
            dx = list(b["diagnoses"]) + ([b["diagnosis_other"]] if b.get("diagnosis_other") else [])
            self.table.setItem(r, 1, QTableWidgetItem("; ".join(dx)))
            self.table.setItem(r, 2, QTableWidgetItem(b.get("updated_at") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(b.get("updated_by") or ""))
        if biopsies:
            self.table.selectRow(self.table.rowCount() - 1)
