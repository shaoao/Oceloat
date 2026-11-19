"""资源管理器：管 Ocelot 数据目录里的文件。

它不再是一块「指标看板」，而是一个只针对应用数据目录的小文件管理器：

- 面包屑导航 + 向上的返回，路径点哪层进哪层；
- 按名称 / 大小 / 修改时间排序，带筛选框；
- 双击进入文件夹、打开文件，右键菜单，悬停出行内「在 Finder 中显示 / 删除」；
- 新建文件夹、重命名、删除（走系统废纸篓，能捡回来）；
- 顶部一行占用概览 + 一个「清理旧文件」（过期回收站、30 天前备份、分析缓存）。

内存/健康度那套看板已经整体搬走：定时回收在 ``app/memtrim.py``，
开关在「设置 → 通用」。这里只谈存储，不再谈内存。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .dialogs import GlassDialog
from .theme import C, font, mono, theme
from .widgets import (
    Button,
    Card,
    Divider,
    Label,
    SmoothScrollArea,
    fade_in,
    icon_button,
)

# ------------------------------------------------------------------ 格式化

_UNITS = ("B", "KB", "MB", "GB", "TB")

# 三列宽度：跟 SortHeader 共用，改一处就够
SIZE_W = 78
TIME_W = 108
ACT_W = 58
ROW_H = 30


def human_bytes(n: Any, digits: int = 1) -> str:
    """1536 -> '1.5 KB'。负数、None、非数字统一给「—」。"""
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if value < 0 else ""
    value = abs(value)
    for i, unit in enumerate(_UNITS):
        if value < 1024 or i == len(_UNITS) - 1:
            if unit == "B":
                return f"{sign}{value:.0f} {unit}"
            return f"{sign}{value:.{digits}f} {unit}"
        value /= 1024
    return "—"


def human_count(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_mtime(ts: float) -> str:
    """今天只给时分，今年给月日，更早给年月日 —— 一列 12 个字符以内说完。"""
    try:
        when = datetime.fromtimestamp(float(ts))
    except (ValueError, OSError, OverflowError):
        return "—"
    now = datetime.now()
    if when.date() == now.date():
        return when.strftime("%H:%M")
    if when.year == now.year:
        return when.strftime("%m-%d %H:%M")
    return when.strftime("%Y-%m-%d")


def _q(color: Any) -> QColor:
    if isinstance(color, QColor):
        return QColor(color)
    return C(color)


def _alpha(color: Any, a: int) -> QColor:
    c = _q(color)
    c.setAlpha(max(0, min(255, a)))
    return c


# ------------------------------------------------------------------ 文件操作


def app_root() -> Path:
    from .store import APP_DIR

    return APP_DIR


def icon_for(path: Path) -> str:
    if path.is_dir():
        return "folder"
    ext = path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".icns"):
        return "image"
    if ext in (".json", ".py", ".js", ".ts", ".yaml", ".yml", ".toml", ".sh"):
        return "code"
    if ext in (".csv", ".tsv", ".xlsx", ".xls"):
        return "table"
    return "file"


def entry_size(path: Path) -> int:
    """文件给真实字节；目录给 0（递归扫描太贵，列表里显示「—」更诚实）。"""
    try:
        return 0 if path.is_dir() else path.stat().st_size
    except OSError:
        return 0


def list_entries(path: Path, query: str = "", sort_key: str = "name",
                 reverse: bool = False) -> List[Path]:
    """列目录：目录永远排在文件前面，再按所选列排序。"""
    try:
        entries = [p for p in path.iterdir()]
    except OSError:
        return []
    query = (query or "").strip().lower()
    if query:
        entries = [p for p in entries if query in p.name.lower()]

    if sort_key == "size":
        entries.sort(key=lambda p: (not p.is_dir(), entry_size(p), p.name.lower()))
    elif sort_key == "time":
        def mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        entries.sort(key=lambda p: (not p.is_dir(), mtime(p), p.name.lower()))
    else:
        entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
    if reverse:
        # 反转时别把「目录优先」也反掉：目录块内部倒序，文件块仍在其后
        dirs = [p for p in entries if p.is_dir()]
        files = [p for p in entries if not p.is_dir()]
        entries = list(reversed(dirs)) + list(reversed(files))
    return entries


def reveal(path: Path) -> bool:
    """在系统文件管理器里选中这个文件（Finder / 资源管理器 / 文件）。"""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
        return True
    except Exception:  # noqa: BLE001
        return False


def open_path(path: Path) -> bool:
    if path.is_dir():
        return False
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))


def to_trash(path: Path) -> Tuple[bool, str]:
    """移进系统废纸篓，而不是直接 unlink —— 手滑还能捡回来。

    返回 (成功, 失败原因)。系统废纸篓用不了时，退到应用自己的 ``.trash`` 目录。
    """
    try:
        if sys.platform == "darwin":
            safe = str(path).replace('"', '\\"')
            script = f'tell application "Finder" to delete POSIX file "{safe}"'
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, text=True, timeout=12)
            if r.returncode == 0:
                return True, ""
        elif sys.platform.startswith("linux"):
            r = subprocess.run(["gio", "trash", str(path)],
                               capture_output=True, text=True, timeout=12)
            if r.returncode == 0:
                return True, ""
    except Exception:  # noqa: BLE001
        pass

    # 兜底：挪到数据目录下的 .trash，文件名加时间戳，不覆盖旧文件
    try:
        bucket = app_root() / ".trash"
        bucket.mkdir(parents=True, exist_ok=True)
        target = bucket / f"{int(time.time())}-{path.name}"
        shutil.move(str(path), str(target))
        return True, str(target)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ------------------------------------------------------------------ 占用概览

GROUP_META: Dict[str, str] = {
    "state": "状态文件",
    "backup": "自动备份",
    "log": "运行日志",
    "other": "其它文件",
}

STORAGE_TOKENS = {"state": "accent", "backup": "info",
                  "log": "warning", "other": "text_faint"}


def _group_of(name: str) -> str:
    if name == "state.json":
        return "state"
    if name.startswith("state.json.bak"):
        return "backup"
    if name.endswith(".log"):
        return "log"
    return "other"


def _path_size(path: Path) -> Tuple[int, int]:
    if path.is_dir():
        total = 0
        files = 0
        for root, _dirs, names in os.walk(path):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    files += 1
                except OSError:
                    continue
        return total, files
    try:
        return path.stat().st_size, 1
    except OSError:
        return 0, 0


def storage_scan(root: Path) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, int]] = {key: {"size": 0, "files": 0} for key in GROUP_META}
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        size, files = _path_size(entry)
        bucket = groups[_group_of(entry.name)]
        bucket["size"] += size
        bucket["files"] += files
    disk = {"total": 0, "used": 0, "free": 0}
    try:
        usage = shutil.disk_usage(str(root if root.exists() else Path.home()))
        disk = {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        pass
    return {
        "root": str(root),
        "total": sum(g["size"] for g in groups.values()),
        "files": sum(g["files"] for g in groups.values()),
        "groups": [{"key": k, "size": v["size"], "files": v["files"]}
                   for k, v in groups.items()],
        "disk": disk,
    }


def data_assets(store: Any, tabs: int = 0) -> Dict[str, int]:
    """数据资产计数：底部概览用来回答「删掉这个会不会丢东西」。"""
    requests = 0
    folders = 0
    try:
        for node, _siblings in store.walk():
            if node.get("type") == "folder":
                folders += 1
            else:
                requests += 1
    except Exception:  # noqa: BLE001
        pass

    def size_of(attr: str) -> int:
        try:
            return len(getattr(store, attr) or [])
        except Exception:  # noqa: BLE001
            return 0

    return {
        "requests": requests,
        "folders": folders,
        "collections": size_of("collections"),
        "history": size_of("history"),
        "trash": size_of("trash"),
        "environments": size_of("environments"),
        "tabs": tabs,
    }


def free_backups(root: Path, days: int = 30, keep: int = 3) -> Tuple[int, int]:
    """删掉 N 天前的 state.json.bak*，返回 (个数, 字节)。

    只碰自己的备份，而且**永远留最近 keep 份**：哪怕全是老文件，也有三份能退回去。
    这些备份现在就是存档损坏时的救命绳，不能为了省几百 KB 全清掉。
    """
    cutoff = time.time() - days * 86400
    count = 0
    freed = 0
    try:
        entries = sorted(root.glob("state.json.bak*"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return 0, 0
    for path in entries[keep:]:
        try:
            if path.stat().st_mtime > cutoff:
                continue
            size = path.stat().st_size
            path.unlink()
            count += 1
            freed += size
        except OSError:
            continue
    return count, freed


# ------------------------------------------------------------------ 自绘控件


class Dot(QWidget):
    """6px 圆点：图例、分节标题前面那一点颜色。"""

    def __init__(self, token: str = "accent", size: int = 6, parent=None):
        super().__init__(parent)
        self._token = token
        self._size = size
        self.setFixedSize(size + 3, size + 3)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_q(getattr(theme(), self._token, theme().text_dim)))
        p.drawEllipse(QRectF(1.5, 1.5, self._size, self._size))
        p.end()


class StackBar(QWidget):
    """一条把所有类别串起来的占比条，段间留 2px 空隙。"""

    def __init__(self, height: int = 8, parent=None):
        super().__init__(parent)
        self._segs: List[Tuple[float, Any]] = []
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_segments(self, segs: List[Tuple[float, Any]]) -> None:
        self._segs = [(max(0.0, float(v)), c) for v, c in segs]
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(t.text, 16))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        segs = [(v, c) for v, c in self._segs if v > 0]
        total = sum(v for v, _ in segs)
        if total > 0:
            gap = 2.0 if len(segs) > 1 else 0.0
            usable = w - gap * (len(segs) - 1)
            x = 0.0
            for value, color in segs:
                seg_w = max(3.0, usable * (value / total))
                p.setBrush(_q(color))
                p.drawRoundedRect(QRectF(x, 0, seg_w, h), h / 2, h / 2)
                x += seg_w + gap
        p.end()


def _columns(width: int) -> Tuple[float, float, float]:
    """(名称右边界, 大小右边界, 时间右边界)。行与表头共用。"""
    time_right = float(width) - ACT_W - 8
    size_right = time_right - TIME_W
    name_right = size_right - SIZE_W
    return name_right, size_right, time_right


class SortHeader(QWidget):
    """三列可点的表头：再点一次换方向。"""

    changed = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.key = "name"
        self.reverse = False
        self._zones: List[Tuple[str, QRectF]] = []

    def set_state(self, key: str, reverse: bool) -> None:
        self.key, self.reverse = key, reverse
        self.update()

    def _layout_zones(self) -> None:
        name_r, size_r, time_r = _columns(self.width())
        self._zones = [
            ("name", QRectF(0, 0, max(10.0, name_r), self.height())),
            ("size", QRectF(name_r, 0, SIZE_W, self.height())),
            ("time", QRectF(size_r, 0, TIME_W, self.height())),
        ]

    def paintEvent(self, _e):
        t = theme()
        self._layout_zones()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        f = font(10.3)
        p.setFont(f)
        arrow = "↑" if not self.reverse else "↓"
        labels = {"name": i18n.tr("名称"), "size": i18n.tr("大小"),
                  "time": i18n.tr("修改时间")}
        for key, rect in self._zones:
            active = key == self.key
            p.setPen(C(t.text_dim if active else t.text_faint))
            text = labels[key] + (f" {arrow}" if active else "")
            align = Qt.AlignmentFlag.AlignRight if key != "name" else Qt.AlignmentFlag.AlignLeft
            p.drawText(rect.adjusted(0, 0, -4 if key != "name" else 0, 0),
                       int(align | Qt.AlignmentFlag.AlignVCenter), text)
        p.setPen(QPen(C(t.border), 1))
        p.drawLine(QPointF(2, self.height() - 0.5),
                   QPointF(self.width() - 2, self.height() - 0.5))
        p.end()

    def mouseReleaseEvent(self, e):
        self._layout_zones()
        x = e.position().x()
        for key, rect in self._zones:
            if rect.left() <= x <= rect.right():
                if key == self.key:
                    self.reverse = not self.reverse
                else:
                    self.key, self.reverse = key, False
                self.update()
                self.changed.emit(self.key, self.reverse)
                return
        super().mouseReleaseEvent(e)


class FileRow(QWidget):
    """一行文件：图标 + 名称 + 大小 + 修改时间，悬停时右侧露出两个动作。"""

    clicked = pyqtSignal(object)
    double_clicked = pyqtSignal(object)
    reveal_clicked = pyqtSignal(object)
    delete_clicked = pyqtSignal(object)
    menu_requested = pyqtSignal(object, QPoint)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.is_dir = path.is_dir()
        self.size_bytes = entry_size(path)
        try:
            self.mtime = path.stat().st_mtime
        except OSError:
            self.mtime = 0.0
        self.selected = False
        self._hover = False
        self._hover_act = ""
        self._font = font(12.4)
        self._small = mono(10.6)
        self.setFixedHeight(ROW_H)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)

    # -------------------------------------------- 命中区
    def _act_rects(self) -> Tuple[QRectF, QRectF]:
        w = float(self.width())
        reveal = QRectF(w - 52, (ROW_H - 20) / 2, 20, 20)
        delete = QRectF(w - 28, (ROW_H - 20) / 2, 20, 20)
        return reveal, delete

    def _act_at(self, pos: QPointF) -> str:
        reveal, delete = self._act_rects()
        if reveal.contains(pos):
            return "reveal"
        if delete.contains(pos):
            return "delete"
        return ""

    def mouseMoveEvent(self, e):
        act = self._act_at(e.position())
        if act != self._hover_act:
            self._hover_act = act
            self.update()
        self.setCursor(Qt.CursorShape.PointingHandCursor if act
                       else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._hover_act = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(e)
        act = self._act_at(e.position())
        if act == "reveal":
            self.reveal_clicked.emit(self.path)
            return
        if act == "delete":
            self.delete_clicked.emit(self.path)
            return
        self.clicked.emit(self.path)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._act_at(e.position()):
            self.double_clicked.emit(self.path)

    def _on_menu(self, pos: QPoint) -> None:
        self.clicked.emit(self.path)
        self.menu_requested.emit(self.path, self.mapToGlobal(pos))

    # -------------------------------------------- 绘制
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 1.0, -0.5, -1.0)
        if self.selected:
            p.setPen(QPen(C(t.border), 1))
            p.setBrush(C(t.elevated))
            p.drawRoundedRect(r, 6, 6)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(r, 6, 6)
        else:
            p.setPen(Qt.PenStyle.NoPen)

        cy = float(ROW_H) / 2
        pm = icons.pixmap(icon_for(self.path),
                          t.accent if self.is_dir else t.text_dim, 15, 1.6)
        p.drawPixmap(QPointF(10, cy - 7.5), pm)

        name_right, size_right, time_right = _columns(self.width())
        # 名称：太长就省略中间，扩展名还能看见
        name_rect = QRectF(33, 0, max(10.0, name_right - 33), float(ROW_H))
        fm = QFontMetricsF(self._font)
        elided = fm.elidedText(self.path.name, Qt.TextElideMode.ElideMiddle,
                               int(name_rect.width()))
        p.setFont(self._font)
        p.setPen(C(t.text))
        p.drawText(name_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   elided)

        p.setFont(self._small)
        p.setPen(C(t.text_dim if self.is_dir else t.text_faint))
        p.drawText(QRectF(name_right, 0, SIZE_W - 12, float(ROW_H)),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   "—" if self.is_dir else human_bytes(self.size_bytes))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(size_right, 0, TIME_W - 12, float(ROW_H)),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   fmt_mtime(self.mtime) if self.mtime else "—")

        # 悬停 / 选中时才画动作，静止状态下列表更安静
        if self._hover or self.selected:
            reveal, delete = self._act_rects()
            for name, rect, token, icon_name in (
                ("reveal", reveal, "text_dim", "external"),
                ("delete", delete, "danger", "trash"),
            ):
                if self._hover_act == name:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(C(t.hover))
                    p.drawRoundedRect(rect, 5, 5)
                col = C(t.danger if token == "danger" and self._hover_act == name else t.text_faint)
                ipm = icons.pixmap(icon_name, col.name(), 13, 1.6)
                p.drawPixmap(QPointF(rect.center().x() - 6.5,
                                     rect.center().y() - 6.5), ipm)
        p.end()


class FileBrowser(QWidget):
    """导航 + 表头 + 列表 + 空状态。外层的操作按钮通过信号同步可用状态。"""

    selection_changed = pyqtSignal(object)      # Path / None
    path_changed = pyqtSignal(object)           # 当前目录
    revealed = pyqtSignal(str)                  # 提示文案
    delete_requested = pyqtSignal(object)       # 行内 / 右键要求删除
    menu_requested = pyqtSignal(object, QPoint)  # 右键菜单

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.path = root
        self.sort_key = "name"
        self.reverse = False
        self._rows: List[FileRow] = []
        self._selected: Optional[Path] = None
        self._query = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(6)
        self.up_btn = icon_button("chevron_left", "返回上级  ⌫", 26, 14)
        self.up_btn.clicked.connect(self.go_up)
        nav.addWidget(self.up_btn)
        self.crumbs = QWidget()
        self.crumbs_lay = QHBoxLayout(self.crumbs)
        self.crumbs_lay.setContentsMargins(0, 0, 0, 0)
        self.crumbs_lay.setSpacing(2)
        nav.addWidget(self.crumbs, 0)
        nav.addStretch(1)
        self.filter = QLineEdit()
        self.filter.setObjectName("Field")
        self.filter.setFixedSize(168, 26)
        self.filter.setFont(font(11.4))
        i18n.placeholder(self.filter, "筛选文件…")
        self.filter.textChanged.connect(self._on_filter)
        nav.addWidget(self.filter, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(nav)

        self.header = SortHeader()
        self.header.changed.connect(self._on_sort)
        lay.addWidget(self.header)

        self.scroll = SmoothScrollArea()
        self.host = QWidget()
        self.list_lay = QVBoxLayout(self.host)
        self.list_lay.setContentsMargins(0, 2, 2, 2)
        self.list_lay.setSpacing(1)
        self.list_lay.addStretch(1)
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.viewport().setAutoFillBackground(False)
        self.host.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.host)
        lay.addWidget(self.scroll, 1)

        self.empty = Label("", 11.4, theme().text_faint)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        lay.addWidget(self.empty, 1)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.set_path(root)

    # -------------------------------------------- 导航
    def set_path(self, path: Path, select: Optional[Path] = None) -> None:
        try:
            target = path if path.is_dir() else self.root
        except OSError:
            target = self.root
        try:
            target.relative_to(self.root)
        except ValueError:
            # 指到数据目录外面了：把它当成新的根，面包屑从这一层重新起算
            self.root = target
        self.path = target
        self._selected = select
        self._rebuild_crumbs()
        self.reload()
        self.path_changed.emit(target)

    def go_up(self) -> None:
        if self.path == self.root:
            return
        parent = self.path.parent
        try:
            parent.relative_to(self.root)
        except ValueError:
            return          # 不让人越过「数据目录」往上翻
        self.set_path(parent, select=self.path)

    def _rebuild_crumbs(self) -> None:
        while self.crumbs_lay.count():
            item = self.crumbs_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        # 从数据目录一路到当前层：每一层都能点
        chain = [self.root]
        try:
            rel = self.path.relative_to(self.root)
            for part in rel.parts:
                chain.append(chain[-1] / part)
        except ValueError:
            chain = [self.path]
        for i, node in enumerate(chain):
            if i:
                sep = Label("›", 11, theme().text_faint)
                self.crumbs_lay.addWidget(sep, 0, Qt.AlignmentFlag.AlignVCenter)
            text = ("数据目录" if node == app_root() else node.name) if i == 0 else node.name
            btn = Button(text, None, kind="ghost", height=24, padding=7,
                         font_size=11.6, radius=5)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            last = i == len(chain) - 1
            if last:
                btn.setStyleSheet("background: transparent;")
            btn.clicked.connect(lambda _=False, p=node: self.set_path(p))
            self.crumbs_lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def _on_filter(self, text: str) -> None:
        self._query = text.strip()
        self.reload(keep_query=True)

    def _on_sort(self, key: str, reverse: bool) -> None:
        self.sort_key, self.reverse = key, reverse
        self.header.set_state(key, reverse)
        self.reload()

    # -------------------------------------------- 列表
    def reload(self, keep_query: bool = True) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        entries = list_entries(self.path, self._query, self.sort_key, self.reverse)
        for entry in entries:
            row = FileRow(entry, self.host)
            row.clicked.connect(self._select)
            row.double_clicked.connect(self._activate)
            row.reveal_clicked.connect(self._reveal)
            row.delete_clicked.connect(self.delete_requested.emit)
            row.menu_requested.connect(self.menu_requested.emit)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
            self._rows.append(row)

        if self._selected is not None:
            self._apply_selection(self._selected)
        empty = not entries
        self.empty.setVisible(empty)
        self.scroll.setVisible(not empty)
        if empty:
            self.empty.setText(
                i18n.tr("没有匹配的文件") if self._query else i18n.tr("这个文件夹是空的"))
        self.up_btn.setEnabled(self.path != self.root)

    def _apply_selection(self, path: Optional[Path]) -> None:
        self._selected = path
        for row in self._rows:
            row.selected = bool(path is not None and row.path == path)
            row.update()
        self.selection_changed.emit(path)

    def _select(self, path: Path) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._apply_selection(path)

    def _activate(self, path: Path) -> None:
        if path.is_dir():
            self.set_path(path)
        else:
            if not open_path(path):
                self.revealed.emit(i18n.tr("这个文件没有默认打开方式"))
                reveal(path)
            else:
                self.revealed.emit(i18n.trf("已用默认方式打开 {name}", name=path.name))

    def _reveal(self, path: Path) -> None:
        if reveal(path):
            self.revealed.emit(i18n.tr("已在 Finder 中显示"))
        else:
            self.revealed.emit(i18n.tr("打不开系统文件管理器"))

    def selected(self) -> Optional[Path]:
        return self._selected

    def select_path(self, path: Path) -> None:
        self._apply_selection(path)

    def refresh_entries(self) -> None:
        """外部改过文件（删除 / 重命名）后重读，尽量保留选中项。"""
        keep = self._selected
        self.reload()
        if keep is not None and not keep.exists():
            self._apply_selection(None)

    # -------------------------------------------- 键盘
    def keyPressEvent(self, e):
        key = e.key()
        rows = self._rows
        if not rows:
            return super().keyPressEvent(e)
        idx = next((i for i, r in enumerate(rows) if r.path == self._selected), -1)
        if key == Qt.Key.Key_Down:
            self._select(rows[min(len(rows) - 1, idx + 1)].path)
            self.scroll.ensureWidgetVisible(rows[min(len(rows) - 1, idx + 1)], 0, 24)
            return
        if key == Qt.Key.Key_Up:
            self._select(rows[max(0, idx - 1)].path)
            self.scroll.ensureWidgetVisible(rows[max(0, idx - 1)], 0, 24)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and 0 <= idx < len(rows):
            self._activate(rows[idx].path)
            return
        if key == Qt.Key.Key_Backspace:
            self.go_up()
            return
        super().keyPressEvent(e)


# ------------------------------------------------------------------ 主窗口


class ResourceDialog(GlassDialog):
    """资源管理器：一个只针对应用数据目录的文件管理器。

    刻意不做的事：不再显示进程内存、系统内存、健康分。那些指标看一次知道就够了，
    常驻一块看板只会让人反复盯数字。内存回收改成后台定时（设置 → 通用），
    这里的每一格都对应「一个能立刻动手的操作」。
    """

    BLUR_FIXED = True
    REFRESH_MS = 12000

    def __init__(self, store, parent=None, analysis_cache=None,
                 tabs_count: int = 0, on_data_changed=None):
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        width, height = 880, 600
        if avail is not None:
            width = max(680, min(width, avail.width() - 60))
            height = max(460, min(height, avail.height() - 60))
        super().__init__(parent, width=width, height=height, title="资源管理器")

        self.store = store
        self._cache = analysis_cache
        self._tabs_count = tabs_count
        self._on_data_changed = on_data_changed
        self._legend: Dict[str, Tuple[Dot, Label, Label]] = {}

        self._build_header_tools()
        self._build()
        self.refresh_overview()
        self._sync_buttons(None)
        self._restore_status()

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh_overview)   # 只刷概览，不动列表选择

        self._revert = QTimer(self)
        self._revert.setSingleShot(True)
        self._revert.timeout.connect(self._restore_status)

    # -------------------------------------------------- 构建
    def _build_header_tools(self) -> None:
        lay = self.header.layout()
        if lay is None:
            return
        self.refresh_btn = Button("刷新", "refresh", kind="ghost", height=26,
                                  padding=9, icon_size=12, font_size=11.4, gap=5,
                                  tooltip="重新读一遍目录  ⌘R")
        self.refresh_btn.clicked.connect(self._manual_refresh)
        lay.insertWidget(max(0, lay.count() - 1), self.refresh_btn)

    def _build(self) -> None:
        body = QVBoxLayout(self.body)
        body.setContentsMargins(16, 12, 16, 14)
        body.setSpacing(10)
        body.addWidget(self._build_overview(), 0)
        body.addWidget(self._build_browser(), 1)
        body.addWidget(self._build_actions(), 0)

    def _build_overview(self) -> QWidget:
        card = Card(radius=12)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 10, 14, 11)
        box.setSpacing(7)

        row = QHBoxLayout()
        row.setSpacing(9)
        row.addWidget(Label("应用数据", 10.6, theme().text_faint), 0,
                       Qt.AlignmentFlag.AlignBottom)
        self.total_label = Label("—", 19.0, theme().text,
                                 weight=QFont.Weight.DemiBold, spacing=-0.3)
        row.addWidget(self.total_label, 0, Qt.AlignmentFlag.AlignBottom)
        self.files_label = Label("", 10.6, theme().text_faint)
        row.addWidget(self.files_label, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        self.clean_btn = Button("清理旧文件", "broom", kind="ghost", height=25,
                                padding=9, icon_size=12, font_size=11.2, gap=5,
                                tooltip="清掉过期回收站、30 天前的自动备份与 AI 分析缓存（最近的备份永远保留）")
        self.clean_btn.clicked.connect(self._act_clean)
        row.addWidget(self.clean_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(row)

        self.bar = StackBar(7)
        box.addWidget(self.bar)

        legend = QHBoxLayout()
        legend.setSpacing(12)
        for key in ("state", "backup", "log", "other"):
            item = QHBoxLayout()
            item.setSpacing(5)
            dot = Dot(STORAGE_TOKENS[key], 5)
            name = Label(GROUP_META[key], 10.2, theme().text_faint)
            value = Label("—", 10.2, theme().text_dim, mono_font=True)
            item.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            item.addWidget(name, 0, Qt.AlignmentFlag.AlignVCenter)
            item.addWidget(value, 0, Qt.AlignmentFlag.AlignVCenter)
            legend.addLayout(item)
            self._legend[key] = (dot, name, value)
        legend.addStretch(1)
        self.disk_label = Label("", 10.2, theme().text_faint)
        legend.addWidget(self.disk_label, 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(legend)
        return card

    def _build_browser(self) -> QWidget:
        card = Card(radius=12)
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 10, 12, 8)
        box.setSpacing(6)

        self.browser = FileBrowser(app_root())
        self.browser.selection_changed.connect(self._on_selection)
        self.browser.path_changed.connect(lambda _p: self._restore_status())
        self.browser.revealed.connect(self._say_info)
        self.browser.delete_requested.connect(self._delete)
        self.browser.menu_requested.connect(self._show_menu)
        box.addWidget(self.browser, 1)
        return card

    def _build_actions(self) -> QWidget:
        card = Card(radius=12)
        card.setFixedHeight(50)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 0, 13, 0)
        lay.setSpacing(8)

        self.reveal_btn = Button("在 Finder 中显示", "external", kind="ghost", height=27,
                                 padding=10, icon_size=12, font_size=11.4, gap=6,
                                 tooltip="在系统文件管理器里定位当前目录")
        self.reveal_btn.clicked.connect(self._act_reveal)
        self.new_btn = Button("新建文件夹", "plus", kind="ghost", height=27,
                              padding=10, icon_size=12, font_size=11.4, gap=6,
                              tooltip="在当前目录下建一个文件夹")
        self.new_btn.clicked.connect(self._act_new_folder)
        self.rename_btn = Button("重命名", "pencil", kind="ghost", height=27,
                                 padding=10, icon_size=12, font_size=11.4, gap=6,
                                 tooltip="重命名选中项  ↩")
        self.rename_btn.clicked.connect(self._act_rename)
        self.delete_btn = Button("删除", "trash", kind="danger", height=27,
                                 padding=10, icon_size=12, font_size=11.4, gap=6,
                                 tooltip="移到系统废纸篓  ⌫")
        self.delete_btn.clicked.connect(self._act_delete)

        for btn in (self.reveal_btn, self.new_btn):
            lay.addWidget(btn)
        lay.addStretch(1)
        self.status = Label("", 10.5, theme().text_faint)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.status, 0)
        for btn in (self.rename_btn, self.delete_btn):
            lay.addWidget(btn)
        return card

    # -------------------------------------------------- 概览
    def refresh_overview(self) -> None:
        try:
            data = storage_scan(app_root())
        except Exception:  # noqa: BLE001
            return
        self.total_label.setText(human_bytes(data["total"]))
        self.files_label.setText(i18n.trf("{n} 个文件", n=human_count(data["files"])))
        colors = {k: getattr(theme(), tok) for k, tok in STORAGE_TOKENS.items()}
        self.bar.set_segments([(g["size"], colors[g["key"]]) for g in data["groups"]])
        for g in data["groups"]:
            refs = self._legend.get(g["key"])
            if refs is not None:
                refs[2].setText(human_bytes(g["size"]))
        disk = data["disk"]
        if disk["total"]:
            free_pct = disk["free"] / disk["total"] * 100
            self.disk_label.setText(i18n.trf(
                "磁盘剩余 {free}（{pct}%）",
                free=human_bytes(disk["free"]), pct=f"{free_pct:.0f}"))
        else:
            self.disk_label.setText("")

    def _manual_refresh(self) -> None:
        self.browser.reload()
        self.refresh_overview()
        self.refresh_btn.spin_once(520)
        self._say_info(i18n.tr("已刷新"))

    # -------------------------------------------------- 状态栏
    def _sync_buttons(self, path: Optional[Path]) -> None:
        has = path is not None
        self.rename_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)

    def _selection_text(self) -> str:
        path = self.browser.selected()
        total = len(self.browser._rows)
        if path is None:
            return i18n.trf("共 {n} 项", n=human_count(total))
        try:
            is_dir = path.is_dir()
            size = 0 if is_dir else path.stat().st_size
        except OSError:
            is_dir, size = False, 0
        return i18n.trf("已选 {name} · {size}", name=path.name,
                        size="—" if is_dir else human_bytes(size))

    def _on_selection(self, path: Optional[Path]) -> None:
        self._sync_buttons(path)
        if not self._revert.isActive():
            self._set_status(self._selection_text(), theme().text_faint)

    def _set_status(self, text: str, color: str) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")

    def _restore_status(self) -> None:
        self._set_status(self._selection_text(), theme().text_faint)

    def _say(self, text: str, token: str = "success", revert_after: int = 3200) -> None:
        col = {"success": theme().success, "info": theme().text_dim,
               "warning": theme().warning, "danger": theme().danger}.get(token, theme().text_dim)
        self._set_status(text, col)
        fade_in(self.status, 180)
        self._revert.start(revert_after)

    def _say_info(self, text: str) -> None:
        self._say(text, "info")

    # -------------------------------------------------- 操作
    def _act_reveal(self) -> None:
        target = self.browser.selected()
        if target is None:
            target = self.browser.path
        if reveal(target):
            self._say_info(i18n.tr("已在 Finder 中显示"))
        else:
            self._say(i18n.tr("打不开系统文件管理器"), "warning")

    def _act_new_folder(self) -> None:
        from .mock_panel import TextPromptDialog

        dlg = TextPromptDialog("新建文件夹", "文件夹名称", "",
                               "建在当前目录下", self)
        if not dlg.exec():
            return
        name = (dlg.value() or "").strip()
        if not name:
            return
        try:
            (self.browser.path / name).mkdir()
            self.browser.reload()
            self.browser.select_path(self.browser.path / name)
            self.refresh_overview()
            self._say(i18n.trf("已新建 {name}", name=name))
        except OSError as exc:
            self._say(i18n.trf("建不了：{why}", why=str(exc)), "danger")

    def _act_rename(self) -> None:
        path = self.browser.selected()
        if path is None:
            return
        from .mock_panel import TextPromptDialog

        dlg = TextPromptDialog("重命名", "新名称", path.name, "", self)
        if not dlg.exec():
            return
        new_name = (dlg.value() or "").strip()
        if not new_name or new_name == path.name:
            return
        try:
            target = path.with_name(new_name)
            if target.exists():
                self._say(i18n.tr("同名文件已存在"), "warning")
                return
            path.rename(target)
            self.browser.reload()
            self.browser.select_path(target)
            self.refresh_overview()
            self._say(i18n.trf("已改名为 {name}", name=new_name))
        except OSError as exc:
            self._say(i18n.trf("改不了：{why}", why=str(exc)), "danger")

    def _act_delete(self) -> None:
        path = self.browser.selected()
        if path is not None:
            self._delete(path)

    def _delete(self, path: Path) -> None:
        from .dialogs import ConfirmDialog

        what = i18n.tr("文件夹") if path.is_dir() else i18n.tr("文件")
        ok = ConfirmDialog.ask(
            self, i18n.tr("删除到废纸篓"),
            i18n.trf("把{what}「{name}」移到废纸篓？还能从系统废纸篓捡回来。",
                     what=what, name=path.name),
            i18n.tr("移到废纸篓"))
        if not ok:
            return
        done, note = to_trash(path)
        if done:
            self.browser.refresh_entries()
            self.refresh_overview()
            self._notify_data_changed()
            self._say(i18n.trf("已删除 {name}", name=path.name))
        else:
            self._say(i18n.trf("删不掉：{why}", why=note), "danger")

    def _show_menu(self, path: Path, pos: QPoint) -> None:
        from .widgets import Menu

        t = theme()
        menu = Menu(self)
        act_open = menu.addAction(icons.icon("external", t.text, 14), "打开")
        act_reveal = menu.addAction(icons.icon("external", t.text_dim, 14), "在 Finder 中显示")
        menu.addSeparator()
        act_copy = menu.addAction(icons.icon("copy", t.text_dim, 14), "复制路径")
        menu.addSeparator()
        act_restore = None
        if path.name.startswith("state.json"):
            menu.addSeparator()
            act_restore = menu.addAction(
                icons.icon("undo", t.accent, 14), "用这份存档恢复")
        menu.addSeparator()
        act_rename = menu.addAction(icons.icon("pencil", t.text, 14), "重命名")
        act_delete = menu.addAction(icons.icon("trash", t.danger, 14), "删除")
        chosen = menu.exec(pos)
        if chosen is act_restore and act_restore is not None:
            self._restore_backup(path)
        elif chosen is act_open:
            self.browser._activate(path)
        elif chosen is act_copy:
            QApplication.clipboard().setText(str(path))
            self._say_info(i18n.tr("已复制路径"))
        elif chosen is act_reveal:
            self.browser._reveal(path)
        elif chosen is act_rename:
            self.browser.select_path(path)
            self._act_rename()
        elif chosen is act_delete:
            self._delete(path)

    def _restore_backup(self, path: Path) -> None:
        """把某份 state.json 备份当成当前存档用（覆盖前自动再备份一次）。"""
        from .dialogs import ConfirmDialog

        try:
            stamp = time.strftime("%m-%d %H:%M", time.localtime(path.stat().st_mtime))
            size = human_bytes(path.stat().st_size)
        except OSError:
            stamp, size = "", ""
        ok = ConfirmDialog.ask(
            self, i18n.tr("用这份备份恢复"),
            i18n.trf("将用「{name}」（{stamp} · {size}）覆盖当前数据。"
                     "当前数据会先自动备份一份，随时能退回来。恢复后建议重启一次窗口。",
                     name=path.name, stamp=stamp, size=size),
            i18n.tr("恢复"))
        if not ok:
            return
        done, why = self.store.restore_from(path)
        if not done:
            self._say_info(i18n.trf("恢复失败：{why}", why=why))
            return
        self.store.save()
        self._notify_data_changed()
        self.browser.reload()
        self.refresh_overview()
        self._say(i18n.trf("已用 {name} 恢复；当前数据已另存为一份备份", name=path.name))

    def _act_clean(self) -> None:
        """清掉「扔了也不丢数据」的四类东西：过期回收站、旧备份、分析缓存、空 .trash。"""
        cached = 0
        if self._cache is not None:
            cached = len(self._cache)
            self._cache.clear()
        trash = 0
        try:
            trash = int(self.store.purge_expired_trash() or 0)
            if trash:
                self.store.save()
                self._notify_data_changed()
        except Exception:  # noqa: BLE001
            trash = 0
        backups, freed = 0, 0
        try:
            backups, freed = free_backups(app_root())
        except Exception:  # noqa: BLE001
            backups, freed = 0, 0
        bucket = app_root() / ".trash"
        try:
            if bucket.is_dir() and not any(bucket.iterdir()):
                bucket.rmdir()
        except OSError:
            pass

        self.clean_btn.spin_once(520)
        self.browser.reload()
        self.refresh_overview()
        parts = []
        if trash:
            parts.append(i18n.trf("{n} 项过期记录", n=trash))
        if backups:
            parts.append(i18n.trf("{n} 个旧备份", n=backups))
        if cached:
            parts.append(i18n.trf("{n} 份分析缓存", n=cached))
        if parts:
            self._say(i18n.trf("已清理 {what} · {v}", what="、".join(parts),
                               v=human_bytes(freed)))
        else:
            self._say_info(i18n.tr("没有需要清理的东西"))

    def _notify_data_changed(self) -> None:
        if callable(self._on_data_changed):
            try:
                self._on_data_changed()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------- 事件
    def showEvent(self, e):
        super().showEvent(e)
        self.browser.reload()
        self.refresh_overview()
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if (e.key() == Qt.Key.Key_R
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._manual_refresh()
            return
        if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # ⌫ 在列表里是「回上级」，这里只接 Delete
            if e.key() == Qt.Key.Key_Delete and self.browser.selected() is not None:
                self._act_delete()
                return
        super().keyPressEvent(e)

    def done(self, result: int) -> None:
        self._timer.stop()
        self._revert.stop()
        super().done(result)

    def refresh_i18n(self) -> None:
        self._restore_status()

