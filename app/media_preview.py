"""响应预览：图片（缩放 / 拖动）、音频、视频、PDF、二进制十六进制。

不依赖系统播放器，音视频用 QtMultimedia；模块缺失时优雅降级为「另存为」。
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from PyQt6.QtCore import QRectF, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .theme import C, font, mono, theme
from .widgets import Button, EmptyState, HBox, Label, VBox

try:  # 音视频是可选项
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtMultimediaWidgets import QVideoWidget

    _MULTIMEDIA = True
except Exception:  # noqa: BLE001
    _MULTIMEDIA = False


# ---------------------------------------------------------------- 图片


class ImageView(QWidget):
    """图片查看：滚轮缩放、拖拽平移、双击自适应。"""

    def __init__(self, data: bytes, parent=None):
        super().__init__(parent)
        self._pm = QPixmap()
        self._pm.loadFromData(data)
        self._zoom = 1.0
        self._fit = True
        self._offset = [0.0, 0.0]
        self._drag: Optional[tuple] = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setMinimumHeight(160)

    def has_image(self) -> bool:
        return not self._pm.isNull()

    def size_hint_px(self) -> tuple:
        return (self._pm.width(), self._pm.height())

    def reset_fit(self) -> None:
        self._fit = True
        self._zoom = 1.0
        self._offset = [0.0, 0.0]
        self.update()

    def set_zoom(self, factor: float) -> None:
        self._fit = False
        self._zoom = max(0.05, min(16.0, factor))
        self.update()

    def zoom_by(self, step: float) -> None:
        self.set_zoom((self._zoom if not self._fit else self._fit_scale()) * step)

    def _fit_scale(self) -> float:
        if self._pm.isNull():
            return 1.0
        return min(self.width() / max(self._pm.width(), 1),
                   self.height() / max(self._pm.height(), 1), 1.0)

    def _scale(self) -> float:
        return self._fit_scale() if self._fit else self._zoom

    # -------------------------------------------------- 事件
    def wheelEvent(self, e):
        if self._pm.isNull():
            return
        delta = e.angleDelta().y()
        self.zoom_by(1.12 if delta > 0 else 1 / 1.12)

    def mouseDoubleClickEvent(self, e):
        if self._fit:
            self.set_zoom(1.0)
        else:
            self.reset_fit()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = (e.position().x(), e.position().y(), self._offset[0], self._offset[1])
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        x0, y0, ox, oy = self._drag
        self._offset = [ox + e.position().x() - x0, oy + e.position().y() - y0]
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), C(t.code_bg))
        if self._pm.isNull():
            p.setPen(C(t.text_faint))
            p.setFont(font(12))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "无法解码这张图片")
            p.end()
            return
        # 透明区棋盘格
        if self._pm.hasAlphaChannel():
            p.setPen(Qt.PenStyle.NoPen)
            cell = 9
            dark = QColor(0, 0, 0, 26)
            for row in range(0, self.height(), cell):
                for col in range(0, self.width(), cell):
                    if (row // cell + col // cell) % 2 == 0:
                        p.fillRect(col, row, cell, cell, dark)
        s = self._scale()
        w, h = self._pm.width() * s, self._pm.height() * s
        x = (self.width() - w) / 2 + self._offset[0]
        y = (self.height() - h) / 2 + self._offset[1]
        p.drawPixmap(QRectF(x, y, w, h), self._pm, QRectF(self._pm.rect()))
        p.end()


def suggested_name(resp, default: str = "response") -> str:
    from urllib.parse import urlparse

    name = os.path.basename(urlparse(resp.url or "").path) or default
    return name[:120]


def save_bytes(parent: QWidget, data: bytes, name: str) -> bool:
    path, _ = QFileDialog.getSaveFileName(parent, "保存到本地", name)
    if not path:
        return False
    try:
        with open(path, "wb") as f:
            f.write(data)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- 音视频

_EXT_BY_TYPE = {
    "wav": "wav", "wave": "wav", "x-wav": "wav", "vnd.wave": "wav",
    "mpeg": "mp3", "mp3": "mp3", "mpeg3": "mp3",
    "ogg": "ogg", "opus": "opus", "flac": "flac", "flac+ogg": "flac",
    "aac": "aac", "aacp": "aac", "mp4": "m4a", "x-m4a": "m4a", "m4a": "m4a",
    "webm": "webm", "quicktime": "mov", "matroska": "mkv", "x-msvideo": "avi",
}


def _media_ext(data: bytes, content_type: str, video: bool) -> str:
    """先看魔术字节，再按 MIME 猜；猜不到才退回 bin。"""
    head = data[:16]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[4:8] == b"ftyp":
        return "m4a" if not video else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    for sub in str(content_type or "").lower().split(";")[0].split("/")[-1].split("+"):
        sub = sub.strip()
        if sub in _EXT_BY_TYPE:
            return _EXT_BY_TYPE[sub]
    return "mp4" if video else "bin"


class MediaPlayer(QWidget):
    """音频 / 视频：播放、进度、音量、另存为。"""

    def __init__(self, data: bytes, content_type: str, video: bool = False, parent=None,
                 filename: str = "media"):
        super().__init__(parent)
        self._filename = filename
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"reqly_preview_{abs(hash(data)) % 10 ** 8}."
            + _media_ext(data, content_type, video))
        try:
            with open(self._tmp, "wb") as f:
                f.write(data)
        except Exception:  # noqa: BLE001
            self._tmp = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.setSpacing(12)

        self._player = None
        self._audio = None
        if _MULTIMEDIA and self._tmp:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setVolume(0.7)
            self._player.setAudioOutput(self._audio)
            if video:
                self.video = QVideoWidget()
                self.video.setMinimumHeight(240)
                self._player.setVideoOutput(self.video)
                lay.addWidget(self.video, 1)
            else:
                art = QLabel()
                art.setAlignment(Qt.AlignmentFlag.AlignCenter)
                from . import icons

                art.setPixmap(icons.pixmap("audio", theme().text_dim, 54, 1.5))
                lay.addWidget(art, 1)
            self._player.setSource(QUrl.fromLocalFile(self._tmp))
        else:
            lay.addWidget(EmptyState("audio", "无法在应用内播放",
                                     "缺少 QtMultimedia 模块，可另存为后用系统播放器打开"), 1)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.play_btn = Button("播放", "play", kind="primary", height=30, padding=14, font_size=12)
        self.play_btn.clicked.connect(self._toggle)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._seek)
        self.time_lbl = Label("00:00 / 00:00", 10.5, theme().text_faint, mono_font=True)
        self.save_btn = Button("保存", "download", kind="ghost", height=28, padding=10, font_size=11.5)
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.play_btn)
        row.addWidget(self.slider, 1)
        row.addWidget(self.time_lbl)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        if self._player is not None:
            self._player.positionChanged.connect(self._on_pos)
            self._player.durationChanged.connect(self._on_dur)
            self._player.playbackStateChanged.connect(self._on_state)

    def _toggle(self) -> None:
        if self._player is None:
            return
        from PyQt6.QtMultimedia import QMediaPlayer as MP

        if self._player.playbackState() == MP.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _seek(self, v: int) -> None:
        if self._player is not None:
            self._player.setPosition(int(self._player.duration() * v / 1000))

    def _on_pos(self, pos: int) -> None:
        if self._player is None or not self._player.duration():
            return
        self.slider.setValue(int(pos * 1000 / self._player.duration()))
        self.time_lbl.setText(f"{_mmss(pos)} / {_mmss(self._player.duration())}")

    def _on_dur(self, dur: int) -> None:
        self.time_lbl.setText(f"00:00 / {_mmss(dur)}")

    def _on_state(self, state) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer as MP

        playing = state == MP.PlaybackState.PlayingState
        self.play_btn.setText("暂停" if playing else "播放")
        self.play_btn.set_icon("stop" if playing else "play")

    def _save(self) -> None:
        if not self._tmp:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存到本地", self._filename)
        if path:
            try:
                with open(self._tmp, "rb") as src, open(path, "wb") as dst:
                    dst.write(src.read())
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())


def _mmss(ms: int) -> str:
    s = max(0, int(ms // 1000))
    return f"{s // 60:02d}:{s % 60:02d}"


# ---------------------------------------------------------------- 十六进制


class HexView(QWidget):
    def __init__(self, data: bytes, parent=None):
        super().__init__(parent)
        self.data = data[:8192]
        self.setMinimumHeight(160)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.fillRect(self.rect(), C(t.code_bg))
        p.setFont(mono(10.5))
        fm = QFontMetricsF(p.font())
        lh = fm.height()
        rows = max(0, (self.height() - 16) // int(lh))
        for r in range(min(rows, len(self.data) // 16 + 1)):
            chunk = self.data[r * 16:(r + 1) * 16]
            if not chunk:
                break
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(12, 8 + r * lh, 60, lh),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       f"{r * 16:06X}")
            p.setPen(C(t.text_dim))
            hexs = " ".join(f"{b:02x}" for b in chunk)
            p.drawText(QRectF(78, 8 + r * lh, 400, lh),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), hexs)
            text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(486, 8 + r * lh, 200, lh),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        p.end()


def build_preview(resp, host: QWidget, layout: QVBoxLayout) -> None:
    """按响应类型往 layout 里塞一个预览控件。"""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            if hasattr(w, "stop"):
                try:
                    w.stop()
                except Exception:  # noqa: BLE001
                    pass
            w.setParent(None)
            w.deleteLater()

    kind = resp.kind
    if kind == "image":
        view = ImageView(resp.body)
        if view.has_image():
            bar = QWidget()
            bl = QHBoxLayout(bar)
            bl.setContentsMargins(0, 0, 0, 6)
            bl.setSpacing(6)
            wpx, hpx = view.size_hint_px()
            info = Label(f"{wpx} × {hpx}", 10.5, theme().text_faint, mono_font=True)
            fit_btn = Button("适应窗口", None, kind="ghost", height=22, padding=7, font_size=11)
            fit_btn.clicked.connect(view.reset_fit)
            one_btn = Button("1:1", None, kind="ghost", height=22, padding=7, font_size=11)
            one_btn.clicked.connect(lambda: view.set_zoom(1.0))
            zin = Button("放大", None, kind="ghost", height=22, padding=7, font_size=11)
            zin.clicked.connect(lambda: view.zoom_by(1.25))
            zout = Button("缩小", None, kind="ghost", height=22, padding=7, font_size=11)
            zout.clicked.connect(lambda: view.zoom_by(1 / 1.25))
            save_btn = Button("保存", "download", kind="ghost", height=22, padding=7, font_size=11,
                              tooltip="把这张图片保存到本地")
            save_btn.clicked.connect(lambda: save_bytes(host, resp.body, suggested_name(resp, "image.png")))
            bl.addWidget(info)
            bl.addStretch(1)
            for b in (zout, zin, one_btn, fit_btn, save_btn):
                bl.addWidget(b)
            layout.addWidget(bar)
            layout.addWidget(view, 1)
            return
    if kind in ("audio", "video"):
        layout.addWidget(MediaPlayer(resp.body, resp.content_type, video=(kind == "video"),
                                     filename=suggested_name(resp, "media")), 1)
        return
    if kind in ("pdf", "binary"):
        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 6)
        bl.setSpacing(6)
        title = ("PDF 响应" if kind == "pdf"
                 else f"二进制内容 · {len(resp.body)} 字节 · 仅显示前 8 KB")
        bl.addWidget(Label(title, 10.5, theme().text_faint, mono_font=True))
        bl.addStretch(1)
        save_btn = Button("保存", "download", kind="ghost", height=22, padding=7, font_size=11)
        save_btn.clicked.connect(
            lambda: save_bytes(host, resp.body, suggested_name(resp, "response.bin")))
        bl.addWidget(save_btn)
        layout.addWidget(bar)
        if kind == "pdf":
            layout.addWidget(EmptyState("file", "PDF 响应", "保存后用系统阅读器打开"), 1)
        else:
            layout.addWidget(HexView(resp.body), 1)
        return
    layout.addWidget(EmptyState("file", "没有可预览的内容",
                                "这个响应不是图片 / 音频 / 视频，切到「美化」看正文"), 1)
