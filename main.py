
import sys, json, socket, os, tempfile
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QFrame, QStackedWidget,
    QSlider, QComboBox, QDialog, QSizePolicy, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QUrl,
    QEasingCurve, QPropertyAnimation, QVariantAnimation, QAbstractAnimation,
)
from PyQt6.QtGui  import QFont, QCursor, QColor, QPainter, QPen
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# ── Palette ───────────────────────────────────────────────────────────────────
C = dict(
    bg='#0C0C0C', surf='#141414', card='#1C1C1C', card2='#242424',
    y='#FFD700',  y2='#FFC200',   y3='#CC9900',   org='#FF8C00',
    tx='#FFFFFF', tx2='#999999',  tx3='#555555',
    div='#272727', ok='#4CAF50',  err='#F44336',  like='#FF4444',
)

STYLE = f"""
QMainWindow {{ background:{C['bg']}; }}
QWidget      {{ font-family:'Segoe UI',Arial,sans-serif; color:{C['tx']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background:transparent; border:none; }}
QScrollBar:vertical {{
    background:transparent; width:5px; border-radius:2px; margin:0;
}}
QScrollBar::handle:vertical {{
    background:{C['div']}; border-radius:2px; min-height:30px;
}}
QScrollBar::handle:vertical:hover  {{ background:{C['y3']}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical      {{ height:0; border:none; }}
QLineEdit {{
    background:{C['card']}; border:1.5px solid {C['div']};
    border-radius:10px; padding:10px 16px; color:{C['tx']}; font-size:14px;
}}
QLineEdit:focus {{ border-color:{C['y']}; background:{C['card2']}; }}
QSlider::groove:horizontal {{
    background:{C['div']}; height:4px; border-radius:2px;
}}
QSlider::handle:horizontal {{
    background:{C['y']}; width:14px; height:14px;
    border-radius:7px; margin:-5px 0;
}}
QSlider::sub-page:horizontal {{ background:{C['y']}; border-radius:2px; }}
QComboBox {{
    background:{C['card']}; border:1.5px solid {C['div']};
    border-radius:8px; padding:7px 14px; color:{C['tx']}; font-size:13px;
}}
QComboBox:hover {{ border-color:{C['y']}; }}
QComboBox::drop-down {{ border:none; width:20px; }}
QComboBox QAbstractItemView {{
    background:{C['card']}; border:1px solid {C['y']}; color:{C['tx']};
    selection-background-color:{C['y']}; selection-color:#000;
    padding:2px; outline:none;
}}
"""


def _color_with_alpha(color, alpha):
    c = QColor(color)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def fade_in_widget(widget, duration=220, start=0.0, end=1.0):
    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
    anim.finished.connect(lambda: setattr(widget, "_fade_anim", None))
    widget._fade_anim = anim
    anim.start()


class GlowButton(QPushButton):
    def __init__(
        self, text="", parent=None, *,
        glow_color=None, base_alpha=0, hover_alpha=80, press_alpha=110,
        base_blur=12, hover_blur=24, y_offset=0
    ):
        super().__init__(text, parent)
        self._glow_color = glow_color or C['y']
        self._base_alpha = base_alpha
        self._hover_alpha = hover_alpha
        self._press_alpha = press_alpha
        self._base_blur = base_blur
        self._hover_blur = hover_blur
        self._y_offset = y_offset
        self._hover_level = 0.0
        self._press_level = 0.0
        self._pin_level = 0.0
        self._pulse_level = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_frame)

        self._pulse_anim = QVariantAnimation(self)
        self._pulse_anim.setDuration(1700)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse_anim.valueChanged.connect(self._on_pulse_frame)

    def _on_hover_frame(self, value):
        self._hover_level = float(value)
        self._refresh_glow()

    def _on_pulse_frame(self, value):
        self._pulse_level = float(value)
        self._refresh_glow()

    def _glow_strength(self):
        return max(self._hover_level, self._press_level, self._pin_level, self._pulse_level)

    def _glow_alpha(self):
        level = self._glow_strength()
        alpha = self._base_alpha + (self._hover_alpha - self._base_alpha) * min(level, 1.0)
        if level > 1.0:
            alpha += (self._press_alpha - self._hover_alpha) * min(level - 1.0, 1.0)
        return max(0.0, alpha)

    def _refresh_glow(self):
        self.update()

    def _animate_hover(self, end_value):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_level)
        self._hover_anim.setEndValue(end_value)
        self._hover_anim.start()

    def set_pinned_glow(self, level=1.0):
        self._pin_level = max(0.0, float(level))
        self._refresh_glow()

    def set_pulse(self, enabled):
        if enabled:
            if self._pulse_anim.state() != QAbstractAnimation.State.Running:
                self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse_level = 0.0
            self._refresh_glow()

    def enterEvent(self, e):
        self._animate_hover(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._press_level = 0.0
        self._animate_hover(0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._press_level = 1.18
        self._refresh_glow()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press_level = 1.0 if self.underMouse() else 0.0
        self._refresh_glow()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        level = self._glow_strength()
        if level <= 0.01:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        glow_alpha = self._glow_alpha()
        radius = max(8.0, min(self.height() / 2.0, 22.0))
        rounds = (
            (1.0, 0.48, 1.2),
            (2.0, 0.26, 1.9),
            (3.0, 0.14, 2.8),
        )
        for inset, alpha_mul, width in rounds:
            color = _color_with_alpha(self._glow_color, glow_alpha * alpha_mul)
            pen = QPen(color, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawRoundedRect(
                self.rect().adjusted(int(inset), int(inset), -int(inset), -int(inset)),
                radius, radius
            )


class GlowLineEdit(QLineEdit):
    def __init__(self, *args, glow_color=None, focus_alpha=85, **kwargs):
        super().__init__(*args, **kwargs)
        self._glow_color = glow_color or C['y']
        self._focus_alpha = focus_alpha
        self._focus_level = 0.0

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, 0)
        self._shadow.setBlurRadius(12)
        self._shadow.setColor(_color_with_alpha(self._glow_color, 0))
        self.setGraphicsEffect(self._shadow)

        self._focus_anim = QVariantAnimation(self)
        self._focus_anim.setDuration(180)
        self._focus_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._focus_anim.valueChanged.connect(self._on_focus_frame)

    def _on_focus_frame(self, value):
        self._focus_level = float(value)
        self._shadow.setBlurRadius(12 + 10 * self._focus_level)
        self._shadow.setColor(_color_with_alpha(self._glow_color, self._focus_alpha * self._focus_level))

    def _animate_focus(self, end_value):
        self._focus_anim.stop()
        self._focus_anim.setStartValue(self._focus_level)
        self._focus_anim.setEndValue(end_value)
        self._focus_anim.start()

    def focusInEvent(self, e):
        self._animate_focus(1.0)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._animate_focus(0.0)
        super().focusOutEvent(e)


class HoverFrame(QFrame):
    def __init__(
        self, *args, glow_color=None, base_alpha=0, hover_alpha=65,
        base_blur=12, hover_blur=22, y_offset=4, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._glow_color = glow_color or C['y']
        self._base_alpha = base_alpha
        self._hover_alpha = hover_alpha
        self._base_blur = base_blur
        self._hover_blur = hover_blur
        self._y_offset = y_offset
        self._hover_level = 0.0
        self._pin_level = 0.0

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setOffset(0, self._y_offset)
        self._shadow.setBlurRadius(self._base_blur)
        self._shadow.setColor(_color_with_alpha(self._glow_color, self._base_alpha))
        self.setGraphicsEffect(self._shadow)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_frame)

    def _on_hover_frame(self, value):
        self._hover_level = float(value)
        self._refresh_glow()

    def _refresh_glow(self):
        level = max(self._hover_level, self._pin_level)
        alpha = self._base_alpha + (self._hover_alpha - self._base_alpha) * level
        blur = self._base_blur + (self._hover_blur - self._base_blur) * level
        self._shadow.setBlurRadius(blur)
        self._shadow.setColor(_color_with_alpha(self._glow_color, alpha))

    def _animate_hover(self, end_value):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_level)
        self._hover_anim.setEndValue(end_value)
        self._hover_anim.start()

    def set_pinned_glow(self, level=1.0):
        self._pin_level = max(0.0, float(level))
        self._refresh_glow()

    def enterEvent(self, e):
        self._animate_hover(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._animate_hover(0.0)
        super().leaveEvent(e)

# ── Button / label helpers ────────────────────────────────────────────────────
_BTN_GLOW = {
    'primary':    dict(glow_color=C['y'], hover_alpha=120, press_alpha=160, base_blur=16, hover_blur=28),
    'secondary':  dict(glow_color=C['y'], hover_alpha=70,  press_alpha=100, base_blur=12, hover_blur=22),
    'ghost':      dict(glow_color=C['y'], hover_alpha=42,  press_alpha=62,  base_blur=10, hover_blur=18),
    'icon':       dict(glow_color=C['y'], hover_alpha=65,  press_alpha=95,  base_blur=10, hover_blur=20),
    'play':       dict(glow_color=C['y'], hover_alpha=145, press_alpha=180, base_blur=18, hover_blur=32),
    'nav':        dict(glow_color=C['y'], hover_alpha=22,  press_alpha=38,  base_blur=8,  hover_blur=16),
    'nav_active': dict(glow_color=C['y'], hover_alpha=58,  press_alpha=72,  base_blur=10, hover_blur=18),
}

_BTN_SS = {
    'primary': f"""
        QPushButton {{
            background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['y']}, stop:1 {C['org']});
            color:#000; border:none; border-radius:10px;
            font-weight:bold; padding:0 20px;
        }}
        QPushButton:hover   {{ background:{C['y2']}; }}
        QPushButton:pressed {{ background:{C['y3']}; }}
        QPushButton:disabled{{ background:{C['div']}; color:{C['tx3']}; }}
    """,
    'secondary': f"""
        QPushButton {{
            background:{C['card']}; color:{C['tx']};
            border:1.5px solid {C['div']}; border-radius:10px; padding:0 16px;
        }}
        QPushButton:hover   {{ border-color:{C['y']}; background:{C['card2']}; }}
        QPushButton:pressed {{ background:{C['div']}; }}
    """,
    'ghost': f"""
        QPushButton {{
            background:transparent; color:{C['tx2']};
            border:none; border-radius:8px; padding:0 10px;
        }}
        QPushButton:hover   {{ color:{C['y']}; background:rgba(255,215,0,0.08); }}
        QPushButton:pressed {{ background:rgba(255,215,0,0.15); }}
    """,
    'icon': f"""
        QPushButton {{
            background:transparent; color:{C['tx2']}; border:none;
            border-radius:18px; padding:0;
            min-width:36px; max-width:36px;
            min-height:36px; max-height:36px;
        }}
        QPushButton:hover   {{ color:{C['y']}; background:rgba(255,215,0,0.10); }}
        QPushButton:pressed {{ background:rgba(255,215,0,0.20); }}
    """,
    'play': f"""
        QPushButton {{
            background:{C['y']}; color:#000; border:none;
            border-radius:22px; font-weight:bold; padding:0;
            min-width:44px; max-width:44px;
            min-height:44px; max-height:44px;
        }}
        QPushButton:hover   {{ background:{C['y2']}; }}
        QPushButton:pressed {{ background:{C['y3']}; }}
    """,
    'nav': f"""
        QPushButton {{
            background:transparent; color:{C['tx2']}; border:none;
            border-radius:10px; text-align:left;
            padding:0 12px; font-size:13px;
        }}
        QPushButton:hover {{ background:{C['card']}; color:{C['tx']}; }}
    """,
    'nav_active': f"""
        QPushButton {{
            background:rgba(255,215,0,0.10); color:{C['y']}; border:none;
            border-radius:10px; text-align:left;
            padding:0 12px; font-size:13px; font-weight:bold;
            border-left:3px solid {C['y']};
        }}
    """,
}

def mkbtn(text, style='primary', fs=13, fw=None, fh=38, bold=None):
    b = GlowButton(text, **_BTN_GLOW.get(style, _BTN_GLOW['primary']))
    b.setFixedHeight(fh)
    if fw: b.setFixedWidth(fw)
    f = QFont('Segoe UI', fs)
    f.setBold(bold if bold is not None else style == 'primary')
    b.setFont(f)
    b.setStyleSheet(_BTN_SS.get(style, _BTN_SS['primary']))
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    return b

def mklbl(text, fs=13, bold=False, color=None, align=Qt.AlignmentFlag.AlignLeft, wrap=False):
    l = QLabel(text)
    f = QFont('Segoe UI', fs); f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or C['tx']}; background:transparent;")
    l.setAlignment(align)
    if wrap: l.setWordWrap(True)
    return l

def mksep():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{C['div']}; border:none; max-height:1px;")
    return f

def fmt_dur(s):
    if not s: return "0:00"
    return f"{int(s)//60}:{int(s)%60:02d}"


# ══════════════════════════════════════════════════════════════════════════════
#  DIALOGS
# ══════════════════════════════════════════════════════════════════════════════
_DLG_BASE = f"""
    QDialog {{
        background:{C['card']}; border-radius:14px;
        border:1px solid {C['div']};
    }}
    QLabel {{
        color:{C['tx']}; background:transparent; font-size:13px;
    }}
    QLineEdit {{
        background:{C['card2']}; color:{C['tx']};
        border:1.5px solid {C['div']}; border-radius:8px;
        padding:9px 14px; font-size:14px;
    }}
    QLineEdit:focus {{ border-color:{C['y']}; }}
    QComboBox {{
        background:{C['card2']}; color:{C['tx']};
        border:1.5px solid {C['div']}; border-radius:8px;
        padding:9px 14px; font-size:14px;
    }}
    QComboBox:hover {{ border-color:{C['y']}; }}
    QComboBox QAbstractItemView {{
        background:{C['card2']}; color:{C['tx']};
        selection-background-color:{C['y']}; selection-color:#000;
        border:1px solid {C['y']}; outline:none; padding:2px;
    }}
"""

def _dlg_btn(text, primary=True, danger=False):
    b = GlowButton(text, glow_color=C['err'] if danger else C['y'], hover_alpha=115 if primary or danger else 55, press_alpha=145 if primary or danger else 75, base_blur=12, hover_blur=22)
    b.setFixedHeight(40)
    b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    b.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
    if danger:
        ss = (f"QPushButton{{background:{C['err']};color:#fff;border:none;"
              f"border-radius:8px;padding:0 22px;}}"
              f"QPushButton:hover{{background:#EF5350;}}"
              f"QPushButton:pressed{{background:#C62828;}}")
    elif primary:
        ss = (f"QPushButton{{background:{C['y']};color:#000;border:none;"
              f"border-radius:8px;padding:0 22px;}}"
              f"QPushButton:hover{{background:{C['y2']};}}"
              f"QPushButton:pressed{{background:{C['y3']};}}")
    else:
        ss = (f"QPushButton{{background:{C['card2']};color:{C['tx2']};"
              f"border:1px solid {C['div']};border-radius:8px;padding:0 22px;}}"
              f"QPushButton:hover{{background:{C['div']};color:{C['tx']};}}"
              f"QPushButton:pressed{{background:{C['bg']};}}")
    b.setStyleSheet(ss)
    return b

def _dlg_title(text):
    l = QLabel(text)
    l.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
    l.setStyleSheet(f"color:{C['y']}; background:transparent;")
    return l


def ask_text(parent, title, label, placeholder="", default=""):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(360)
    dlg.setStyleSheet(_DLG_BASE)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(14)
    lay.addWidget(_dlg_title(title))
    lay.addWidget(mklbl(label, 12, color=C['tx2']))
    inp = GlowLineEdit()
    inp.setPlaceholderText(placeholder)
    inp.setText(default)
    inp.setFixedHeight(44)
    lay.addWidget(inp)
    row = QHBoxLayout(); row.setSpacing(10)
    cancel = _dlg_btn("Отмена", primary=False)
    ok_b   = _dlg_btn("Создать")
    row.addWidget(cancel); row.addWidget(ok_b)
    lay.addLayout(row)
    inp.returnPressed.connect(ok_b.click)
    ok_b.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)
    if dlg.exec() == QDialog.DialogCode.Accepted and inp.text().strip():
        return inp.text().strip(), True
    return "", False


def ask_choice(parent, title, label, items):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(360)
    dlg.setStyleSheet(_DLG_BASE)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(14)
    lay.addWidget(_dlg_title(title))
    lay.addWidget(mklbl(label, 12, color=C['tx2']))
    combo = QComboBox()
    combo.addItems(items)
    combo.setFixedHeight(44)
    lay.addWidget(combo)
    row = QHBoxLayout(); row.setSpacing(10)
    cancel = _dlg_btn("Отмена", primary=False)
    ok_b   = _dlg_btn("Выбрать")
    row.addWidget(cancel); row.addWidget(ok_b)
    lay.addLayout(row)
    ok_b.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return combo.currentText(), True
    return "", False


def show_info(parent, title, message):
    _notify(parent, title, message, C['ok'])

def show_error(parent, title, message):
    _notify(parent, title, message, C['err'])

def _notify(parent, title, message, color):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(320)
    dlg.setStyleSheet(_DLG_BASE)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(28, 24, 28, 24)
    lay.setSpacing(14)
    hdr = QLabel(title)
    hdr.setFont(QFont('Segoe UI', 15, QFont.Weight.Bold))
    hdr.setStyleSheet(f"color:{color}; background:transparent;")
    lay.addWidget(hdr)
    msg = mklbl(message, 13, color=C['tx2'], wrap=True)
    lay.addWidget(msg)
    ok_b = _dlg_btn("ОК")
    ok_b.clicked.connect(dlg.accept)
    lay.addWidget(ok_b)
    dlg.exec()


# ══════════════════════════════════════════════════════════════════════════════
#  NETWORK
# ══════════════════════════════════════════════════════════════════════════════
class NetThread(QThread):
    ok  = pyqtSignal(dict)
    err = pyqtSignal(str)

    def __init__(self, host, port, msg):
        super().__init__()
        self.host, self.port, self.msg = host, port, msg

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(15)
            s.connect((self.host, self.port))
            s.sendall(json.dumps(self.msg, ensure_ascii=False).encode())
            buf = b""
            while True:
                chunk = s.recv(65536)
                if not chunk: break
                buf += chunk
                try:
                    self.ok.emit(json.loads(buf.decode())); break
                except json.JSONDecodeError:
                    continue
            s.close()
        except ConnectionRefusedError:
            self.err.emit("Сервер недоступен — запустите сервер.py")
        except socket.timeout:
            self.err.emit("Нет ответа от сервера (timeout)")
        except Exception as e:
            self.err.emit(str(e))


class Net:
    HOST = 'localhost'
    PORT = 5555
    _pool: list = []

    @classmethod
    def req(cls, msg, on_ok, on_err=None):
        t = NetThread(cls.HOST, cls.PORT, msg)
        t.ok.connect(on_ok)
        if on_err: t.err.connect(on_err)
        t.finished.connect(lambda: cls._pool.remove(t) if t in cls._pool else None)
        cls._pool.append(t)
        t.start()
        return t


# ══════════════════════════════════════════════════════════════════════════════
#  SONG CARD
# ══════════════════════════════════════════════════════════════════════════════
_CARD_SS = f"""
QFrame#SC {{
    background:{C['card']}; border-radius:10px; border:1px solid {C['div']};
}}
QFrame#SC:hover {{ background:{C['card2']}; border-color:rgba(255,215,0,0.35); }}
"""
_CARD_PLAY_SS = f"""
QFrame#SC {{
    background:rgba(255,215,0,0.07); border-radius:10px;
    border:1px solid rgba(255,215,0,0.45);
}}
"""

class SongCard(HoverFrame):
    play_req   = pyqtSignal(dict)
    like_req   = pyqtSignal(str)
    add_pl_req = pyqtSignal(dict)

    def __init__(self, song: dict, num: int = 0, liked: bool = False):
        super().__init__(glow_color=C['y'], hover_alpha=78, base_blur=14, hover_blur=24, y_offset=3)
        self.song  = song
        self.liked = liked
        self.setObjectName("SC")
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(_CARD_SS)
        self.set_pinned_glow(0.0)
        self._build(num)

    def _build(self, num):
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)

        n = mklbl(f"{num:02d}" if num else "♪", 11, color=C['tx3'])
        n.setFixedWidth(24)
        n.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(n)

        art = QLabel("♪")
        art.setFixedSize(42, 42)
        art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art.setStyleSheet(f"""
            background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #1A1A1A, stop:1 #0A0A0A);
            border-radius:8px; color:{C['y']}; font-size:16px;
        """)
        row.addWidget(art)

        info = QVBoxLayout(); info.setSpacing(2); info.setContentsMargins(0, 0, 0, 0)
        t = mklbl(self.song.get('title', '?'), 13, bold=True)
        t.setMaximumWidth(210)
        a = mklbl(
            f"{self.song.get('artist','?')}  ·  {fmt_dur(self.song.get('duration'))}",
            11, color=C['tx2']
        )
        info.addWidget(t); info.addWidget(a)
        row.addLayout(info, 1)

        pl = mklbl(f"▶ {self.song.get('plays',0)}", 11, color=C['tx3'])
        pl.setFixedWidth(52)
        pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(pl)

        genre = self.song.get('genre', '')
        if genre:
            g = QLabel(genre)
            g.setFixedWidth(62)
            g.setAlignment(Qt.AlignmentFlag.AlignCenter)
            g.setFont(QFont('Segoe UI', 10))
            g.setStyleSheet(f"color:{C['y3']}; background:rgba(255,215,0,0.07); border-radius:4px; padding:2px 4px;")
            row.addWidget(g)

        self.like_btn = GlowButton('', glow_color=C['like'], hover_alpha=70, press_alpha=95, base_blur=8, hover_blur=16)
        self.like_btn.setFixedSize(30, 30)
        self.like_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_like()
        self.like_btn.clicked.connect(lambda: self.like_req.emit(self.song.get('id', '')))
        row.addWidget(self.like_btn)

        add = GlowButton("＋", glow_color=C['y'], hover_alpha=60, press_alpha=85, base_blur=8, hover_blur=16)
        add.setFixedSize(30, 30)
        add.setToolTip("Добавить в плейлист")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{C['tx3']}; border:none;
                border-radius:15px; font-size:15px; font-weight:bold; }}
            QPushButton:hover {{ color:{C['y']}; background:rgba(255,215,0,0.10); }}
        """)
        add.clicked.connect(lambda: self.add_pl_req.emit(self.song))
        row.addWidget(add)

    def _refresh_like(self):
        if self.liked:
            self.like_btn.setText("♥")
            self.like_btn.setStyleSheet(f"""
                QPushButton {{ background:transparent; color:{C['like']}; border:none;
                    border-radius:15px; font-size:16px; }}
                QPushButton:hover {{ background:rgba(255,68,68,0.10); }}
            """)
        else:
            self.like_btn.setText("♡")
            self.like_btn.setStyleSheet(f"""
                QPushButton {{ background:transparent; color:{C['tx3']}; border:none;
                    border-radius:15px; font-size:16px; }}
                QPushButton:hover {{ color:{C['like']}; background:rgba(255,68,68,0.10); }}
            """)

    def set_liked(self, v): self.liked = v; self._refresh_like()
    def set_playing(self, v):
        self.setStyleSheet(_CARD_PLAY_SS if v else _CARD_SS)
        self.set_pinned_glow(1.15 if v else 0.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if not isinstance(self.childAt(e.pos()), QPushButton):
                self.play_req.emit(self.song)
        super().mousePressEvent(e)


def _songs_container():
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 4, 20)
    v.setSpacing(4)
    scroll.setWidget(w)
    return scroll, v

def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget(): item.widget().deleteLater()

def _fill_songs(layout, songs, liked_ids, play_cb, like_cb, add_pl_cb, empty_text="Пусто"):
    _clear_layout(layout)
    if not songs:
        layout.addWidget(
            mklbl(empty_text, 14, color=C['tx2'], align=Qt.AlignmentFlag.AlignCenter))
    else:
        for i, s in enumerate(songs):
            card = SongCard(s, i + 1, s.get('id', '') in liked_ids)
            card.play_req.connect(play_cb)
            card.like_req.connect(like_cb)
            card.add_pl_req.connect(add_pl_cb)
            layout.addWidget(card)
    layout.addStretch()


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH PAGE
# ══════════════════════════════════════════════════════════════════════════════
class AuthPage(QWidget):
    authenticated = pyqtSignal(str, list)

    def __init__(self):
        super().__init__()
        self._mode = 'login'
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(230)
        left.setStyleSheet(f"""
            background:qlineargradient(x1:0,y1:0,x2:0.6,y2:1,
                stop:0 {C['y']}, stop:0.6 {C['org']}, stop:1 #4A0000);
        """)
        ll = QVBoxLayout(left)
        ll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.setContentsMargins(24, 0, 24, 0)
        ll.setSpacing(8)
        ll.addWidget(mklbl("🎵", 54, color='#000', align=Qt.AlignmentFlag.AlignCenter))
        ll.addWidget(mklbl("BeatStream", 22, bold=True, color='#000',
                           align=Qt.AlignmentFlag.AlignCenter))
        ll.addSpacing(8)
        ll.addWidget(mklbl("Твоя музыка,\nтвоё настроение", 12,
                           color='rgba(0,0,0,0.65)',
                           align=Qt.AlignmentFlag.AlignCenter, wrap=True))

        right = QWidget()
        right.setStyleSheet(f"background:{C['surf']};")
        rl = QVBoxLayout(right)
        rl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rl.setContentsMargins(60, 40, 60, 40)

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{ background:{C['card']}; border-radius:18px;
                border:1px solid {C['div']}; }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 36, 36, 32)
        cl.setSpacing(14)

        self.title_l = mklbl("Добро пожаловать", 20, bold=True)
        self.sub_l   = mklbl("Войдите в аккаунт", 13, color=C['tx2'])
        cl.addWidget(self.title_l)
        cl.addWidget(self.sub_l)
        cl.addSpacing(4)

        self.user_e  = GlowLineEdit(); self.user_e.setPlaceholderText("Имя пользователя")
        self.user_e.setFixedHeight(44)
        self.pass_e  = GlowLineEdit(); self.pass_e.setPlaceholderText("Пароль")
        self.pass_e.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_e.setFixedHeight(44)
        self.email_e = GlowLineEdit(); self.email_e.setPlaceholderText("Email (необязательно)")
        self.email_e.setFixedHeight(44)
        self.email_e.setVisible(False)

        cl.addWidget(self.user_e)
        cl.addWidget(self.pass_e)
        cl.addWidget(self.email_e)

        self.msg_l = mklbl("", 12, color=C['err'], align=Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.msg_l)

        self.auth_btn = mkbtn("ВОЙТИ", 'primary', fs=14, fh=46)
        self.auth_btn.clicked.connect(self._do_auth)
        self.pass_e.returnPressed.connect(self._do_auth)
        cl.addWidget(self.auth_btn)
        cl.addSpacing(2)

        sw = QHBoxLayout()
        sw.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_l = mklbl("Нет аккаунта?", 12, color=C['tx2'])
        self.sw_btn = GlowButton("Зарегистрироваться", glow_color=C['y'], hover_alpha=42, press_alpha=60, base_blur=8, hover_blur=14)
        self.sw_btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{C['y']}; border:none;
                font-size:12px; font-weight:bold; }}
            QPushButton:hover {{ color:{C['y2']}; text-decoration:underline; }}
        """)
        self.sw_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.sw_btn.clicked.connect(self._toggle)
        sw.addWidget(self.hint_l); sw.addWidget(self.sw_btn)
        cl.addLayout(sw)

        rl.addWidget(card)
        root.addWidget(left)
        root.addWidget(right, 1)

    def _toggle(self):
        if self._mode == 'login':
            self._mode = 'register'
            self.title_l.setText("Создать аккаунт")
            self.sub_l.setText("Заполните поля ниже")
            self.auth_btn.setText("ЗАРЕГИСТРИРОВАТЬСЯ")
            self.hint_l.setText("Уже есть аккаунт?")
            self.sw_btn.setText("Войти")
            self.email_e.setVisible(True)
        else:
            self._mode = 'login'
            self.title_l.setText("Добро пожаловать")
            self.sub_l.setText("Войдите в аккаунт")
            self.auth_btn.setText("ВОЙТИ")
            self.hint_l.setText("Нет аккаунта?")
            self.sw_btn.setText("Зарегистрироваться")
            self.email_e.setVisible(False)
        self.msg_l.setText("")

    def _do_auth(self):
        u = self.user_e.text().strip()
        p = self.pass_e.text().strip()
        if not u or not p:
            self._msg("Заполните все обязательные поля"); return
        self.auth_btn.setEnabled(False)
        self.auth_btn.setText("Подключение…")
        if self._mode == 'register':
            Net.req({'type':'register','username':u,'password':p,
                     'email':self.email_e.text().strip()},
                    self._on_reg, self._on_net_err)
        else:
            Net.req({'type':'login','username':u,'password':p},
                    self._on_login, self._on_net_err)

    def _on_reg(self, r):
        self._reset_btn()
        if r.get('type') == 'register_success':
            self._msg("✓ Готово! Теперь войдите.", err=False)
            QTimer.singleShot(1400, self._toggle)
        else:
            self._msg(r.get('message', 'Ошибка'))

    def _on_login(self, r):
        self._reset_btn()
        if r.get('type') == 'login_success':
            self._msg("✓ Вход выполнен", err=False)
            QTimer.singleShot(400, lambda:
                self.authenticated.emit(r.get('username', ''), r.get('liked_songs', [])))
        else:
            self._msg(r.get('message', 'Неверные данные'))

    def _on_net_err(self, e): self._reset_btn(); self._msg(f"⚠ {e}")

    def _reset_btn(self):
        self.auth_btn.setEnabled(True)
        self.auth_btn.setText("ВОЙТИ" if self._mode == 'login' else "ЗАРЕГИСТРИРОВАТЬСЯ")

    def _msg(self, text, err=True):
        c = C['err'] if err else C['ok']
        self.msg_l.setStyleSheet(f"color:{c}; background:transparent;")
        self.msg_l.setText(text)


# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER BAR
# ══════════════════════════════════════════════════════════════════════════════
class PlayerBar(QWidget):
    def __init__(self):
        super().__init__()
        self.player    = QMediaPlayer()
        self.audio_out = QAudioOutput()
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(0.7)
        self.current_song = None
        self._seeking     = False
        self._tmp_files: list = []
        self.setFixedHeight(90)
        self.setStyleSheet(f"background:{C['surf']}; border-top:1px solid {C['div']};")
        self._build()
        self.player.positionChanged.connect(self._on_pos)
        self.player.playbackStateChanged.connect(self._on_state)

    def _build(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(18, 8, 18, 8)
        main.setSpacing(6)

        self.prog = QSlider(Qt.Orientation.Horizontal)
        self.prog.setRange(0, 1000)
        self.prog.setFixedHeight(16)
        self.prog.sliderPressed.connect(lambda: setattr(self, '_seeking', True))
        self.prog.sliderReleased.connect(self._seek)
        main.addWidget(self.prog)

        row = QHBoxLayout(); row.setSpacing(14)

        info = QVBoxLayout(); info.setSpacing(2)
        self.t_lbl = mklbl("Нет треков", 13, bold=True)
        self.t_lbl.setMaximumWidth(240)
        self.a_lbl = mklbl("—", 11, color=C['tx2'])
        info.addWidget(self.t_lbl); info.addWidget(self.a_lbl)
        row.addLayout(info, 2)

        btns = QHBoxLayout(); btns.setSpacing(10)
        btns.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prev_btn = mkbtn("⏮", 'icon', fs=18, fh=36); self.prev_btn.setFixedWidth(36)
        self.play_btn = mkbtn("▶", 'play', fs=18, fh=44); self.play_btn.setFixedWidth(44)
        self.next_btn = mkbtn("⏭", 'icon', fs=18, fh=36); self.next_btn.setFixedWidth(36)
        btns.addWidget(self.prev_btn)
        btns.addWidget(self.play_btn)
        btns.addWidget(self.next_btn)
        row.addLayout(btns, 1)

        right = QHBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.setSpacing(10)
        self.time_lbl = mklbl("0:00 / 0:00", 11, color=C['tx3'])
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100); self.vol.setValue(70); self.vol.setFixedWidth(80)
        self.vol.valueChanged.connect(lambda v: self.audio_out.setVolume(v / 100))
        right.addWidget(self.time_lbl)
        right.addWidget(mklbl("🔊", 13))
        right.addWidget(self.vol)
        row.addLayout(right, 2)

        main.addLayout(row)
        self.play_btn.clicked.connect(self.toggle_play)

    def load_and_play(self, song, file_bytes):
        tmp = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tmp.write(file_bytes); tmp.close()
        self._tmp_files.append(tmp.name)
        self.current_song = song
        self.t_lbl.setText(song.get('title', '?')[:36])
        self.a_lbl.setText(song.get('artist', '?'))
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(tmp.name)))
        self.player.play()
        self._gc_temps()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self): self.player.stop()

    def _on_state(self, st):
        playing = st == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸" if playing else "▶")
        self.play_btn.set_pulse(playing)
        self.play_btn.set_pinned_glow(0.95 if playing else 0.0)

    def _on_pos(self, ms):
        if not self._seeking:
            dur = self.player.duration()
            if dur > 0: self.prog.setValue(int(ms / dur * 1000))
            self.time_lbl.setText(
                f"{fmt_dur(ms//1000)} / {fmt_dur(self.player.duration()//1000)}")

    def _seek(self):
        self._seeking = False
        dur = self.player.duration()
        if dur > 0: self.player.setPosition(int(self.prog.value() / 1000 * dur))

    def _gc_temps(self):
        while len(self._tmp_files) > 4:
            try: os.unlink(self._tmp_files.pop(0))
            except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
#  PAGES
# ══════════════════════════════════════════════════════════════════════════════
class LibraryPage(QWidget):
    play_song = pyqtSignal(dict)
    like_song = pyqtSignal(str)
    add_pl    = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.songs: list = []
        self.liked_ids: set = set()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 0)
        lay.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(mklbl("Библиотека", 22, bold=True))
        hdr.addStretch()
        self.genre_cb = QComboBox(); self.genre_cb.addItem("Все жанры")
        self.genre_cb.setFixedWidth(130)
        self.genre_cb.currentIndexChanged.connect(self._filter_genre)
        self.sort_cb = QComboBox()
        self.sort_cb.addItems(["По названию","По исполнителю","По популярности","По дате"])
        self.sort_cb.setFixedWidth(165)
        self.sort_cb.currentIndexChanged.connect(self._sort)
        refresh = mkbtn("⟳", 'ghost', fs=15, fw=36, fh=36, bold=False)
        refresh.setToolTip("Обновить")
        refresh.clicked.connect(self._do_refresh)
        hdr.addWidget(self.genre_cb); hdr.addWidget(self.sort_cb); hdr.addWidget(refresh)
        lay.addLayout(hdr)
        lay.addWidget(mksep())

        self.cnt_l = mklbl("", 12, color=C['tx2'])
        lay.addWidget(self.cnt_l)

        self.scroll, self.v = _songs_container()
        self.v.addWidget(mklbl("Загрузка…", 14, color=C['tx2'],
                                align=Qt.AlignmentFlag.AlignCenter))
        self.v.addStretch()
        lay.addWidget(self.scroll, 1)

    def set_songs(self, songs, liked_ids):
        self.songs = songs; self.liked_ids = set(liked_ids); self._render()

    def _render(self):
        self.cnt_l.setText(f"{len(self.songs)} треков" if self.songs else "")
        _fill_songs(self.v, self.songs, self.liked_ids,
                    self.play_song, self.like_song, self.add_pl, "Библиотека пуста")

    def update_liked(self, sid, liked):
        self.liked_ids.add(sid) if liked else self.liked_ids.discard(sid)
        for i in range(self.v.count()):
            w = self.v.itemAt(i).widget()
            if isinstance(w, SongCard) and w.song.get('id') == sid: w.set_liked(liked)

    def update_genres(self, genres):
        self.genre_cb.blockSignals(True); self.genre_cb.clear()
        self.genre_cb.addItem("Все жанры")
        for g in genres: self.genre_cb.addItem(g)
        self.genre_cb.blockSignals(False)

    def _sort(self, idx):
        keys = [
            lambda x: x.get('title','').lower(),
            lambda x: x.get('artist','').lower(),
            lambda x: -x.get('plays', 0),
            lambda x: x.get('upload_date',''),
        ]
        self.songs.sort(key=keys[idx]); self._render()

    def _filter_genre(self, idx):
        g = self.genre_cb.currentText()
        Net.req({'type':'get_library','genre':'' if idx==0 else g},
                lambda r: self.set_songs(r.get('songs',[]), list(self.liked_ids)))

    def _do_refresh(self):
        Net.req({'type':'get_library'},
                lambda r: self.set_songs(r.get('songs',[]), list(self.liked_ids)),
                lambda e: None)


class SearchPage(QWidget):
    play_song = pyqtSignal(dict)
    like_song = pyqtSignal(str)
    add_pl    = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.liked_ids: set = set()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 0)
        lay.setSpacing(10)
        lay.addWidget(mklbl("Поиск", 22, bold=True))

        row = QHBoxLayout()
        self.inp = GlowLineEdit()
        self.inp.setPlaceholderText("Название, исполнитель, жанр…")
        self.inp.setFixedHeight(44)
        self.inp.returnPressed.connect(self._search)
        sb = mkbtn("Найти", 'primary', fs=13, fw=88, fh=44)
        sb.clicked.connect(self._search)
        row.addWidget(self.inp, 1); row.addWidget(sb)
        lay.addLayout(row)
        lay.addWidget(mksep())

        self.res_l = mklbl("Введите запрос для поиска", 13, color=C['tx2'])
        lay.addWidget(self.res_l)

        self.scroll, self.v = _songs_container()
        self.v.addStretch()
        lay.addWidget(self.scroll, 1)

    def _search(self):
        q = self.inp.text().strip()
        if not q: return
        self.res_l.setText("Поиск…")
        Net.req({'type':'search_music','query':q}, self._on_res,
                lambda e: self.res_l.setText(f"Ошибка: {e}"))

    def _on_res(self, r):
        songs = r.get('songs', [])
        self.res_l.setText(f"Найдено: {len(songs)}" if songs else "Ничего не найдено")
        _fill_songs(self.v, songs, self.liked_ids,
                    self.play_song, self.like_song, self.add_pl)

    def update_liked(self, sid, liked):
        self.liked_ids.add(sid) if liked else self.liked_ids.discard(sid)
        for i in range(self.v.count()):
            w = self.v.itemAt(i).widget()
            if isinstance(w, SongCard) and w.song.get('id') == sid: w.set_liked(liked)


class LikedPage(QWidget):
    play_song = pyqtSignal(dict)
    like_song = pyqtSignal(str)
    add_pl    = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.liked_ids: set = set()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 0)
        lay.setSpacing(10)
        lay.addWidget(mklbl("Понравилось", 22, bold=True))
        lay.addWidget(mksep())
        self.cnt_l = mklbl("", 12, color=C['tx2'])
        lay.addWidget(self.cnt_l)
        self.scroll, self.v = _songs_container()
        self.v.addStretch()
        lay.addWidget(self.scroll, 1)

    def set_songs(self, songs, liked_ids):
        self.liked_ids = set(liked_ids)
        self.cnt_l.setText(f"{len(songs)} треков" if songs else "")
        _fill_songs(self.v, songs, self.liked_ids,
                    self.play_song, self.like_song, self.add_pl,
                    "Вы ещё не лайкнули ни одного трека  ♡")

    def update_liked(self, sid, liked):
        self.liked_ids.add(sid) if liked else self.liked_ids.discard(sid)
        for i in range(self.v.count()):
            w = self.v.itemAt(i).widget()
            if isinstance(w, SongCard) and w.song.get('id') == sid:
                if not liked: w.deleteLater()
                else: w.set_liked(True)



class PlaylistCard(HoverFrame):
    open_req = pyqtSignal(dict)

    def __init__(self, pl):
        super().__init__(glow_color=C['y'], hover_alpha=72, base_blur=14, hover_blur=24, y_offset=4)
        self.pl = pl
        self.setFixedHeight(66)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet(f"""
            QFrame {{
                background:{C['card']}; border-radius:12px;
                border:1px solid {C['div']};
            }}
            QFrame:hover {{
                background:{C['card2']};
                border-color:rgba(255,215,0,0.3);
            }}
        """)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(14)

        ico = QLabel("📀")
        ico.setFixedSize(40, 40)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(f"font-size:20px; background:{C['card2']}; border-radius:8px;")
        row.addWidget(ico)

        inf = QVBoxLayout()
        inf.setSpacing(2)
        inf.addWidget(mklbl(pl.get('name','?'), 14, bold=True))
        inf.addWidget(mklbl(f"{pl.get('songs_count',0)} треков", 11, color=C['tx2']))
        row.addLayout(inf, 1)

        ob = mkbtn("→", 'ghost', fw=36, fh=36, bold=False)
        ob.clicked.connect(lambda _=False, p=pl: self.open_req.emit(p))
        row.addWidget(ob)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not isinstance(self.childAt(e.pos()), QPushButton):
            self.open_req.emit(self.pl)
        super().mousePressEvent(e)


class PlaylistsPage(QWidget):
    play_song = pyqtSignal(dict)
    like_song = pyqtSignal(str)
    add_pl    = pyqtSignal(dict)
    create_pl = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.playlists: list = []
        self.liked_ids: set = set()
        self._build()

    def _build(self):
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        # ── Список плейлистов ────────────────────────────────────────────────
        lv = QWidget()
        ll = QVBoxLayout(lv)
        ll.setContentsMargins(20, 20, 20, 0)
        ll.setSpacing(10)

        hdr = QHBoxLayout()
        hdr.addWidget(mklbl("Мои плейлисты", 22, bold=True))
        hdr.addStretch()

        nb = GlowButton("＋  Новый плейлист", glow_color=C['y'], hover_alpha=120, press_alpha=160, base_blur=16, hover_blur=28)
        nb.setFixedHeight(38)
        nb.setFont(QFont('Segoe UI', 12, QFont.Weight.Bold))
        nb.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        nb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        nb.setStyleSheet(f"""
            QPushButton {{
                background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['y']}, stop:1 {C['org']});
                color:#000; border:none; border-radius:10px;
                font-weight:bold; padding:0 18px;
            }}
            QPushButton:hover   {{ background:{C['y2']}; }}
            QPushButton:pressed {{ background:{C['y3']}; }}
        """)
        nb.clicked.connect(self._new_playlist)
        hdr.addWidget(nb)
        ll.addLayout(hdr)
        ll.addWidget(mksep())

        self.pl_scroll = QScrollArea(); self.pl_scroll.setWidgetResizable(True)
        self.pl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pl_w = QWidget()
        self.pl_v = QVBoxLayout(self.pl_w)
        self.pl_v.setContentsMargins(0, 0, 4, 20); self.pl_v.setSpacing(8)
        self.pl_v.addStretch()
        self.pl_scroll.setWidget(self.pl_w)
        ll.addWidget(self.pl_scroll, 1)
        self.stack.addWidget(lv)

        # ── Детальный вид ────────────────────────────────────────────────────
        dv = QWidget()
        dl = QVBoxLayout(dv)
        dl.setContentsMargins(20, 20, 20, 0)
        dl.setSpacing(10)

        dhdr = QHBoxLayout()
        back = mkbtn("← Назад", 'ghost', fw=95, fh=36, bold=False)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.det_title = mklbl("", 22, bold=True)
        self.det_cnt   = mklbl("", 12, color=C['tx2'])
        dhdr.addWidget(back); dhdr.addWidget(self.det_title)
        dhdr.addStretch(); dhdr.addWidget(self.det_cnt)
        dl.addLayout(dhdr)
        dl.addWidget(mksep())

        self.det_scroll, self.det_v = _songs_container()
        self.det_v.addStretch()
        dl.addWidget(self.det_scroll, 1)
        self.stack.addWidget(dv)

    def set_playlists(self, pls):
        self.playlists = pls
        _clear_layout(self.pl_v)
        if not pls:
            self.pl_v.addWidget(
                mklbl("Нет плейлистов — создайте первый!", 14,
                      color=C['tx2'], align=Qt.AlignmentFlag.AlignCenter))
        else:
            for pl in pls: self.pl_v.addWidget(self._pl_card(pl))
        self.pl_v.addStretch()

    def _pl_card(self, pl):
        card = PlaylistCard(pl)
        card.open_req.connect(self._open)
        return card

    def _open(self, pl):
        self._current_pl = pl
        self.det_title.setText(pl.get('name','?'))
        self.det_cnt.setText(f"{pl.get('songs_count',0)} треков")
        _fill_songs(self.det_v, pl.get('song_details',[]), self.liked_ids,
                    self.play_song, self.like_song, self.add_pl, "Плейлист пуст")
        self.stack.setCurrentIndex(1)

    def update_liked(self, sid, liked):
        self.liked_ids.add(sid) if liked else self.liked_ids.discard(sid)
        for i in range(self.det_v.count()):
            w = self.det_v.itemAt(i).widget()
            if isinstance(w, SongCard) and w.song.get('id') == sid:
                w.set_liked(liked)

    def _new_playlist(self):
        name, ok = ask_text(self, "Новый плейлист", "Название:",
                            placeholder="Мой плейлист")
        if ok: self.create_pl.emit(name)


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
_NAV = [("🎵","Библиотека"),("🔍","Поиск"),("❤️","Понравилось"),("📀","Плейлисты")]

class Sidebar(QWidget):
    nav_changed = pyqtSignal(int)
    logout_req  = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(196)
        self.setStyleSheet(f"background:{C['surf']}; border-right:1px solid {C['div']};")
        self._btns: list = []
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 22, 10, 18)
        lay.setSpacing(2)
        logo = mklbl("🎵 BeatStream", 15, bold=True, color=C['y'])
        logo.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(logo); lay.addSpacing(18)

        for i, (ico, name) in enumerate(_NAV):
            b = GlowButton(f"  {ico}  {name}", **_BTN_GLOW['nav'])
            b.setFixedHeight(42)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setFont(QFont('Segoe UI', 13))
            b.setStyleSheet(_BTN_SS['nav'])
            b.clicked.connect(lambda _, idx=i: self._select(idx))
            self._btns.append(b); lay.addWidget(b)

        lay.addStretch()
        self.user_l = mklbl("", 12, color=C['tx2'])
        self.user_l.setContentsMargins(8, 0, 0, 0)
        lay.addWidget(self.user_l)

        logout = GlowButton("  🚪  Выйти", glow_color=C['err'], hover_alpha=50, press_alpha=70, base_blur=10, hover_blur=18)
        logout.setFixedHeight(40)
        logout.setFont(QFont('Segoe UI', 13))
        logout.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        logout.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{C['tx2']}; border:none;
                border-radius:10px; text-align:left; padding:0 12px; }}
            QPushButton:hover {{ color:{C['err']}; background:rgba(244,67,54,0.08); }}
        """)
        logout.clicked.connect(self.logout_req)
        lay.addWidget(logout)
        self._select(0)

    def _select(self, idx):
        for i, b in enumerate(self._btns):
            b.setStyleSheet(_BTN_SS['nav_active'] if i==idx else _BTN_SS['nav'])
        self.nav_changed.emit(idx)

    def set_user(self, name): self.user_l.setText(f"👤 {name}")


# ══════════════════════════════════════════════════════════════════════════════
#  APP WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class AppWidget(QWidget):
    logout_req = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.username  = ""
        self.liked_ids: set = set()
        self._songs: list   = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self._nav)
        self.sidebar.logout_req.connect(self.logout_req)
        body.addWidget(self.sidebar)

        self.pages    = QStackedWidget()
        self.lib_pg   = LibraryPage()
        self.srch_pg  = SearchPage()
        self.liked_pg = LikedPage()
        self.pl_pg    = PlaylistsPage()

        for pg in (self.lib_pg, self.srch_pg, self.liked_pg, self.pl_pg):
            pg.play_song.connect(self._play)
            pg.like_song.connect(self._like)
            pg.add_pl.connect(self._add_to_pl_dialog)
            self.pages.addWidget(pg)

        self.pl_pg.create_pl.connect(self._create_playlist)
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        self.player_bar = PlayerBar()
        self.player_bar.prev_btn.clicked.connect(self._prev)
        self.player_bar.next_btn.clicked.connect(self._next)
        root.addWidget(self.player_bar)

    def init_user(self, username, liked_ids):
        self.username  = username
        self.liked_ids = set(liked_ids)
        self.sidebar.set_user(username)
        self._load_library(); self._load_liked(); self._load_playlists()
        self.pl_pg.liked_ids = self.liked_ids  # передаём сразу при входе

    def _load_library(self):
        Net.req({'type':'get_library'}, self._on_library,
                lambda e: show_error(self, "Ошибка", f"Библиотека: {e}"))
        Net.req({'type':'get_genres'},
                lambda r: self.lib_pg.update_genres(r.get('genres',[])))

    def _load_liked(self):
        Net.req({'type':'get_liked_songs','username':self.username},
                lambda r: self.liked_pg.set_songs(r.get('songs',[]), list(self.liked_ids)))

    def _load_playlists(self):
        Net.req({'type':'get_playlists','username':self.username},
                lambda r: self.pl_pg.set_playlists(r.get('playlists',[])))

    def _on_library(self, r):
        self._songs = r.get('songs', [])
        self.lib_pg.set_songs(self._songs, list(self.liked_ids))

    def _nav(self, idx):
        self.pages.setCurrentIndex(idx)
        fade_in_widget(self.pages.currentWidget(), duration=210, start=0.45, end=1.0)

    def _play(self, song):
        Net.req({'type':'get_song_file','song_id':song.get('id')},
                lambda r: self._on_file(r, song),
                lambda e: show_error(self, "Ошибка", str(e)))

    def _mark_current_song(self, sid):
        for layout in (self.lib_pg.v, self.srch_pg.v, self.liked_pg.v, self.pl_pg.det_v):
            for i in range(layout.count()):
                w = layout.itemAt(i).widget()
                if isinstance(w, SongCard):
                    w.set_playing(w.song.get('id') == sid)

    def _on_file(self, r, song):
        if r.get('type') == 'song_file':
            self._mark_current_song(song.get('id'))
            self.player_bar.load_and_play(song, bytes.fromhex(r['file_data']))
        else:
            show_error(self, "Ошибка", r.get('message', 'Ошибка файла'))

    def _prev(self):
        if not self._songs or not self.player_bar.current_song: return
        cid = self.player_bar.current_song.get('id')
        idx = next((i for i,s in enumerate(self._songs) if s.get('id')==cid), -1)
        if idx > 0: self._play(self._songs[idx-1])

    def _next(self):
        if not self._songs or not self.player_bar.current_song: return
        cid = self.player_bar.current_song.get('id')
        idx = next((i for i,s in enumerate(self._songs) if s.get('id')==cid), -1)
        if idx < len(self._songs)-1: self._play(self._songs[idx+1])

    def _like(self, sid):
        Net.req({'type':'like_song','username':self.username,'song_id':sid},
                lambda r: self._on_like(r, sid),
                lambda e: show_error(self, "Ошибка", str(e)))

    def _on_like(self, r, sid):
        if r.get('type') != 'like_success': return
        liked = r.get('action') == 'liked'
        self.liked_ids.add(sid) if liked else self.liked_ids.discard(sid)
        for pg in (self.lib_pg, self.srch_pg, self.liked_pg, self.pl_pg):
            pg.update_liked(sid, liked)
        self._load_liked()

    def _add_to_pl_dialog(self, song):
        if not self.pl_pg.playlists:
            show_info(self, "Плейлисты", "Сначала создайте плейлист!")
            return
        names = [p.get('name','?') for p in self.pl_pg.playlists]
        name, ok = ask_choice(self, "Добавить в плейлист", "Выберите плейлист:", names)
        if not (ok and name): return
        pl = next((p for p in self.pl_pg.playlists if p.get('name') == name), None)
        if not pl: return
        Net.req(
            {'type':'add_to_playlist', 'username':self.username,
             'playlist_id': pl.get('id'), 'song_id': song.get('id')},
            # ── БАГ-ФИКС: перезагружаем плейлисты с сервера ─────────────────
            lambda r: self._on_song_added(r, song, pl),
            lambda e: show_error(self, "Ошибка", e)
        )

    def _on_song_added(self, r, song, pl):
        if r.get('type') == 'song_added':
            show_info(self, "Готово",
                      f"«{song.get('title','?')}» добавлено в «{pl.get('name','?')}»")
            self._load_playlists()   # ← перезагружаем данные с сервера
        else:
            show_error(self, "Ошибка", r.get('message', 'Не удалось добавить трек'))

    def _create_playlist(self, name):
        Net.req({'type':'create_playlist','username':self.username,'name':name},
                lambda r: self._load_playlists()
                          if r.get('type') == 'playlist_created'
                          else show_error(self, "Ошибка", r.get('message','')),
                lambda e: show_error(self, "Ошибка", e))

    def cleanup(self): self.player_bar.stop()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎵 BeatStream")
        self.resize(1060, 700)
        self.setMinimumSize(820, 560)
        self.stack = QStackedWidget()
        self.auth  = AuthPage()
        self.app_w = AppWidget()
        self.stack.addWidget(self.auth)
        self.stack.addWidget(self.app_w)
        self.setCentralWidget(self.stack)
        self.auth.authenticated.connect(self._on_auth)
        self.app_w.logout_req.connect(self._on_logout)

    def _on_auth(self, username, liked_ids):
        self.app_w.init_user(username, liked_ids)
        self.stack.setCurrentIndex(1)
        fade_in_widget(self.app_w, duration=260, start=0.35, end=1.0)

    def _on_logout(self):
        self.app_w.cleanup()
        self.stack.setCurrentIndex(0)
        fade_in_widget(self.auth, duration=220, start=0.4, end=1.0)

    def closeEvent(self, e):
        self.app_w.cleanup(); super().closeEvent(e)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())