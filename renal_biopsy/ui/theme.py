"""介面主題：深藍 + 青色光暈的 AI 風格（配色取自科徽）。"""
import math
import os
import random
import sys

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QIcon, QLinearGradient, QPainter, QPalette, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QWidget

# ---- 配色 ----
BG_DEEP = "#060b1c"
BG = "#0a1330"
PANEL = "#101c3d"
PANEL_2 = "#14234a"
INPUT = "#0d1834"
BORDER = "#22345f"
TEXT = "#e6edf7"
MUTED = "#8ea0c4"
CYAN = "#3ee6ff"
TEAL = "#5ef2c6"
BLUE = "#4f7dff"
GOLD = "#d4b26a"
DANGER = "#ff6b81"


def asset_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "renal_biopsy", "assets", name)
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", name)


def _qss_path(name: str) -> str:
    return asset_path(name).replace("\\", "/")


def app_icon() -> QIcon:
    return QIcon(asset_path("app.ico"))


def logo_pixmap(size: int) -> QPixmap:
    pm = QPixmap(asset_path("logo.png"))
    if pm.isNull():
        return pm
    pm = pm.scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pm.setDevicePixelRatio(2)
    return pm


def glow(widget: QWidget, color: str = CYAN, radius: int = 28, alpha: int = 150):
    eff = QGraphicsDropShadowEffect(widget)
    c = QColor(color)
    c.setAlpha(alpha)
    eff.setColor(c)
    eff.setBlurRadius(radius)
    eff.setOffset(0, 0)
    widget.setGraphicsEffect(eff)


def logo_label(size: int, glow_color: str = CYAN) -> QLabel:
    lbl = QLabel()
    lbl.setPixmap(logo_pixmap(size))
    lbl.setFixedSize(size, size)
    lbl.setAttribute(Qt.WA_TranslucentBackground)
    glow(lbl, glow_color, radius=size // 3, alpha=120)
    return lbl


def apply_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, INPUT),
        (QPalette.AlternateBase, PANEL), (QPalette.ToolTipBase, PANEL_2),
        (QPalette.ToolTipText, TEXT), (QPalette.Text, TEXT), (QPalette.Button, PANEL_2),
        (QPalette.ButtonText, TEXT), (QPalette.BrightText, CYAN), (QPalette.Link, CYAN),
        (QPalette.Highlight, "#1f6fd6"), (QPalette.HighlightedText, "#ffffff"),
        (QPalette.PlaceholderText, "#5d6f96"),
    ]:
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5d6f96"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5d6f96"))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())


STYLESHEET = f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}

QLabel#H1 {{ font-size: 22px; font-weight: 700; color: #ffffff; }}
QLabel#H2 {{ font-size: 17px; font-weight: 700; color: #ffffff; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Chip {{
    background: rgba(62,230,255,0.12); color: {CYAN}; border: 1px solid rgba(62,230,255,0.45);
    border-radius: 11px; padding: 2px 10px; font-size: 12px;
}}
QLabel#ChipGold {{
    background: rgba(212,178,106,0.14); color: {GOLD}; border: 1px solid rgba(212,178,106,0.5);
    border-radius: 11px; padding: 2px 10px; font-size: 12px;
}}
QLabel#Banner {{
    background: rgba(212,178,106,0.15); color: #f3dfae; border: 1px solid rgba(212,178,106,0.5);
    border-radius: 8px; padding: 8px;
}}

QFrame#Card, QWidget#Card {{
    background: rgba(16,28,61,0.92); border: 1px solid {BORDER}; border-radius: 14px;
}}
QFrame#Header {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0b1a45, stop:0.6 #0a1536, stop:1 #071026);
    border-bottom: 1px solid rgba(62,230,255,0.35);
}}

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 5px 8px; selection-background-color: #1f6fd6;
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {CYAN}; background: #0f1d40;
}}
QLineEdit:read-only {{ background: transparent; border: 1px solid transparent; color: {TEAL}; }}
QLineEdit#SearchBox {{
    font-size: 17px; padding: 10px 16px; border-radius: 22px; border: 1px solid #2c4a8a;
    background: #0c1838;
}}
QLineEdit#SearchBox:focus {{ border: 1px solid {CYAN}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button, QSpinBox::down-button {{ border: none; background: transparent; width: 20px; }}
QSpinBox::up-arrow {{ image: url({_qss_path("arrow_up.png")}); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url({_qss_path("arrow_down.png")}); width: 10px; height: 10px; }}
QComboBox::down-arrow {{ image: url({_qss_path("arrow_down.png")}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: #1f6fd6;
}}
QComboBox:disabled, QLineEdit:disabled {{ color: #7d8db0; }}

QPushButton {{
    background: {PANEL_2}; border: 1px solid #2c4170; border-radius: 8px;
    padding: 7px 16px; color: {TEXT};
}}
QPushButton:hover {{ border: 1px solid {CYAN}; background: #182a57; }}
QPushButton:pressed {{ background: #0f1d40; }}
QPushButton:disabled {{ color: #4f5f82; border-color: #1b2849; background: #0e1834; }}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #19c6e6, stop:1 #3f6dff);
    border: none; color: #ffffff; font-weight: 700;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3ee6ff, stop:1 #5a83ff);
}}
QPushButton#Primary:disabled {{ background: #1b2849; color: #4f5f82; }}
QPushButton#Danger {{ border: 1px solid rgba(255,107,129,0.55); color: {DANGER}; background: transparent; }}
QPushButton#Danger:hover {{ background: rgba(255,107,129,0.12); }}
QPushButton#Big {{ font-size: 16px; padding: 14px; border-radius: 12px; }}

QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px 12px; color: {TEXT};
}}
QToolButton:hover {{ background: rgba(62,230,255,0.10); border: 1px solid rgba(62,230,255,0.45); }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3a5288; background: {INPUT};
}}
QCheckBox::indicator:hover {{ border: 1px solid {CYAN}; }}
QCheckBox::indicator:checked {{
    background: {CYAN}; border: 1px solid {CYAN}; image: url({_qss_path("check.png")});
}}
QCheckBox:disabled {{ color: #7d8db0; }}

QListWidget#Nav {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; padding: 6px; outline: 0;
}}
QListWidget#Nav::item {{ padding: 8px 10px; border-radius: 8px; color: #b9c6e2; }}
QListWidget#Nav::item:hover {{ background: rgba(62,230,255,0.08); color: #ffffff; }}
QListWidget#Nav::item:selected {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(62,230,255,0.28), stop:1 rgba(79,125,255,0.10));
    color: #ffffff; border-left: 3px solid {CYAN};
}}
QListWidget {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px; }}
QListWidget::indicator, QTableWidget::indicator {{
    width: 15px; height: 15px; border-radius: 4px; border: 1px solid #3a5288; background: {INPUT};
}}
QListWidget::indicator:checked, QTableWidget::indicator:checked {{
    background: {CYAN}; border: 1px solid {CYAN}; image: url({_qss_path("check.png")});
}}

QTableWidget {{
    background: {INPUT}; alternate-background-color: #0f1c3b; border: 1px solid {BORDER};
    border-radius: 10px; gridline-color: #1c2b52; selection-background-color: rgba(62,230,255,0.25);
    selection-color: #ffffff;
}}
QHeaderView::section {{
    background: {PANEL_2}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    border-right: 1px solid #1c2b52; padding: 6px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {PANEL_2}; border: none; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 12px; margin-top: 14px; padding: 12px 10px 10px 10px;
    background: rgba(16,28,61,0.6);
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {CYAN}; font-weight: 600; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a3e6e; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {CYAN}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a3e6e; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {CYAN}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; width: 8px; }}
QStatusBar {{ background: {BG_DEEP}; color: {MUTED}; border-top: 1px solid #16244a; }}
QMessageBox {{ background: {BG}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
"""


class NeuralBackground(QWidget):
    """會緩慢流動的神經網路背景（AI 風格）。子元件可直接放在上面。"""

    def __init__(self, parent=None, nodes: int = 70, animate: bool = True):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        rnd = random.Random(7)
        self._nodes = [[rnd.random(), rnd.random(),
                        (rnd.random() - 0.5) * 0.0012, (rnd.random() - 0.5) * 0.0012,
                        rnd.random() * math.tau] for _ in range(nodes)]
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._step)
        self._animate = animate

    def showEvent(self, e):
        if self._animate:
            self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _step(self):
        for n in self._nodes:
            n[0] += n[2]
            n[1] += n[3]
            n[4] += 0.05
            for i in (0, 1):
                if n[i] < 0 or n[i] > 1:
                    n[i + 2] *= -1
                    n[i] = min(max(n[i], 0), 1)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0, QColor("#0b1a47"))
        bg.setColorAt(0.55, QColor(BG))
        bg.setColorAt(1, QColor(BG_DEEP))
        p.fillRect(self.rect(), bg)
        halo = QRadialGradient(QPointF(w * 0.3, h * 0.45), max(w, h) * 0.55)
        halo.setColorAt(0, QColor(62, 230, 255, 45))
        halo.setColorAt(1, QColor(62, 230, 255, 0))
        p.fillRect(self.rect(), halo)

        pts = [QPointF(n[0] * w, n[1] * h) for n in self._nodes]
        maxd = min(w, h) * 0.22
        for i, a in enumerate(pts):
            for b in pts[i + 1:]:
                d = math.hypot(a.x() - b.x(), a.y() - b.y())
                if d < maxd:
                    c = QColor(94, 200, 255, int(70 * (1 - d / maxd)))
                    p.setPen(QPen(c, 1))
                    p.drawLine(a, b)
        p.setPen(Qt.NoPen)
        for n, pt in zip(self._nodes, pts):
            pulse = 0.5 + 0.5 * math.sin(n[4])
            g = QRadialGradient(pt, 7 + 3 * pulse)
            g.setColorAt(0, QColor(94, 242, 198, int(160 + 80 * pulse)))
            g.setColorAt(1, QColor(62, 230, 255, 0))
            p.setBrush(g)
            p.drawEllipse(QRectF(pt.x() - 9, pt.y() - 9, 18, 18))
        p.end()
