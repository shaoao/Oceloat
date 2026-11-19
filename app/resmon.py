"""资源管理器：内存、存储与数据资产的实时看板 + 安全维护动作。

这不是又一个设置页。目标是让人一眼看清「这个程序到底占了多少、占在哪、
还能放出多少」，并且能当场动手清理：

- 内存：进程常驻 / 峰值 / 系统压力，2 秒采样画出近 3 分钟趋势；
- 存储：应用数据按类别拆开（状态文件、自动备份、日志、其它），
  百分比条直接看出谁在占地方；
- 运行时：对象类型 Top 5、线程数、控件数，能判断有没有东西在堆积；
- 数据资产：集合 / 请求 / 历史 / 回收站 / 环境 / 标签页；
- 维护：释放内存、清分析缓存、清过期回收站、清旧备份，做完即时回报。

所有测量都用标准库（resource / gc / vm_stat / ps），不引入 psutil。
测量失败一律降级为 0 或 None，界面显示「—」，绝不因为读不到指标而崩。
"""
from __future__ import annotations

import gc
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .dialogs import GlassDialog
from .theme import C, font, mono, theme
from .widgets import Button, Card, Label, SmoothScrollArea, fade_in

# ------------------------------------------------------------------ 工具


_UNITS = ("B", "KB", "MB", "GB", "TB")

# 趋势图的横向时间窗（秒）：90 个点 × 2 秒采样 = 3 分钟
SAMPLE_WINDOW = 180.0


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


def _q(color: Any) -> QColor:
    if isinstance(color, QColor):
        return QColor(color)
    return C(color)


def _alpha(color: Any, a: int) -> QColor:
    c = _q(color)
    c.setAlpha(max(0, min(255, a)))
    return c


def _run(cmd: Sequence[str], timeout: float = 2.0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout or ""
    except Exception:  # noqa: BLE001 - 指标读不到就降级
        return ""


# ------------------------------------------------------------------ 测量


def _current_rss() -> int:
    """当前常驻内存（字节）。

    优先 /proc（Linux）和 libproc（macOS）：都是直接查询，不拉起子进程。
    ps 作为次选；实在读不到就退回峰值 —— 界面宁可显示峰值，也不要空着。
    """
    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as f:
            pages = int(f.read().split()[1])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:  # noqa: BLE001
        pass
    value = _mac_rss()
    if value:
        return value
    if sys.platform.startswith("win"):
        return _peak_rss()
    text = _run(["ps", "-o", "rss=", "-p", str(os.getpid())]).strip()
    try:
        return int(text.split()[0]) * 1024
    except (ValueError, IndexError):
        return _peak_rss()


_PROC_LIB: Any = None


def _mac_rss() -> int:
    """macOS：proc_pidinfo(PROC_PIDTASKINFO) 的 pti_resident_size。

    ps 在沙盒 / 受限环境里常常直接 PermissionError，ctypes 这条路没有这个坑，
    而且比拉起一个子进程快一个数量级（2 秒采样一次，差别很明显）。
    """
    if sys.platform != "darwin":
        return 0
    global _PROC_LIB
    try:
        if _PROC_LIB is None:
            import ctypes
            import ctypes.util

            lib = ctypes.CDLL(ctypes.util.find_library("c") or "/usr/lib/libSystem.B.dylib")
            lib.proc_pidinfo.restype = ctypes.c_int
            lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int,
                                        ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            _PROC_LIB = (ctypes, lib)
        ctypes, lib = _PROC_LIB
        buf = ctypes.create_string_buffer(128)
        if lib.proc_pidinfo(os.getpid(), 4, 0, buf, ctypes.sizeof(buf)) >= 16:
            return int.from_bytes(buf.raw[8:16], "little")
    except Exception:  # noqa: BLE001
        return 0
    return 0


def _peak_rss() -> int:
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except Exception:  # noqa: BLE001
        return 0


def process_memory() -> Dict[str, int]:
    rss = _current_rss()
    peak = _peak_rss()
    return {
        "rss": rss,
        "peak": max(peak, rss),
        "threads": threading.active_count(),
    }


_SYS_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}


def system_memory(ttl: float = 3.0) -> Dict[str, int]:
    """整机内存：total / available / used（字节）。读不到全给 0。

    vm_stat / sysctl 各是一次子进程，2 秒采样一次太浪费；缓存 3 秒，
    界面上完全看不出差别，CPU 占用却降下来。
    """
    now = time.time()
    cached = _SYS_CACHE.get("data")
    if cached and now - float(_SYS_CACHE.get("at") or 0) < ttl:
        return cached
    total = 0
    available = 0
    if sys.platform == "darwin":
        try:
            total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0)
        except ValueError:
            total = 0
        vm = _run(["vm_stat"])
        if vm:
            page = 4096
            m = re.search(r"page size of (\d+) bytes", vm)
            if m:
                page = int(m.group(1))

            def pages(key: str) -> int:
                mm = re.search(rf"{key}:\s+(\d+)\.", vm)
                return int(mm.group(1)) if mm else 0

            available = (pages("Pages free") + pages("Pages inactive")
                         + pages("Pages speculative")) * page
    else:
        try:
            info: Dict[str, int] = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    key, _, rest = line.partition(":")
                    try:
                        info[key.strip()] = int(rest.strip().split()[0]) * 1024
                    except (ValueError, IndexError):
                        continue
            total = info.get("MemTotal", 0)
            available = info.get("MemAvailable", info.get("MemFree", 0))
        except OSError:
            pass
    used = max(0, total - available) if total else 0
    percent = round(used / total * 100, 1) if total else 0.0
    out = {"total": total, "available": available, "used": used, "percent": percent}
    _SYS_CACHE["at"] = now
    _SYS_CACHE["data"] = out
    return out


GROUP_META: Dict[str, str] = {
    "state": "状态文件",
    "backup": "自动备份",
    "log": "运行日志",
    "other": "其它文件",
}


def _group_of(name: str) -> str:
    if name == "state.json":
        return "state"
    if name.startswith("state.json.bak"):
        return "backup"
    if name.endswith(".log"):
        return "log"
    return "other"


def _path_size(path: Path) -> Tuple[int, int]:
    """(总字节, 文件数)。目录递归；读不到的部分跳过。"""
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
    """应用数据目录的构成 + 所在磁盘余量。"""
    groups: Dict[str, Dict[str, int]] = {
        key: {"size": 0, "files": 0} for key in GROUP_META
    }
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        size, files = _path_size(entry)
        bucket = groups[_group_of(entry.name)]
        bucket["size"] += size
        bucket["files"] += files
    total = sum(g["size"] for g in groups.values())
    file_count = sum(g["files"] for g in groups.values())
    disk = {"total": 0, "used": 0, "free": 0}
    try:
        usage = shutil.disk_usage(str(root if root.exists() else Path.home()))
        disk = {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        pass
    return {
        "root": str(root),
        "total": total,
        "files": file_count,
        "groups": [{"key": k, "size": v["size"], "files": v["files"]}
                   for k, v in groups.items()],
        "disk": disk,
    }


def data_assets(store: Any, tabs: int = 0) -> Dict[str, int]:
    """数据资产计数：请求 / 文件夹 / 集合 / 历史 / 回收站 / 环境 / 标签页。"""
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
        "history_limit": int(store.settings.get("history_limit", 240) or 240),
    }


def object_stats(limit: int = 5) -> Dict[str, Any]:
    """按类型统计 Python 对象数量。gc.get_objects() 有成本，只在刷新时调用。"""
    counter: Counter = Counter()
    total = 0
    try:
        for obj in gc.get_objects():
            counter[type(obj).__name__] += 1
            total += 1
    except Exception:  # noqa: BLE001
        pass
    return {"total": total, "top": counter.most_common(limit), "types": len(counter)}


def runtime_stats() -> Dict[str, int]:
    widgets = 0
    try:
        widgets = len(QApplication.allWidgets())
    except Exception:  # noqa: BLE001
        pass
    return {
        "threads": threading.active_count(),
        "widgets": widgets,
        "blocks": int(sys.getallocatedblocks()),
    }


def health_status(mem: Dict[str, int], storage: Dict[str, Any],
                  assets: Dict[str, int], cache_entries: int = 0,
                  expired_trash: int = 0) -> Dict[str, Any]:
    """把各项指标折成一个 0~100 的健康分 + 最多三条提示。

    权重刻意偏保守：只有真的接近上限才扣分，不制造焦虑。
    """
    score = 100
    hints: List[Tuple[str, str]] = []

    pct = float(mem.get("percent") or 0)
    if pct >= 85:
        score -= 30
        hints.append(("danger", "系统内存 {pct}%，其它应用会变慢"))
    elif pct >= 70:
        score -= 14
        hints.append(("warning", "系统内存 {pct}%，余量不多"))
    else:
        hints.append(("success", "系统内存 {pct}%，压力正常"))

    total = int(storage.get("total") or 0)
    if total > 200 * 1024 * 1024:
        score -= 18
        hints.append(("warning", "应用数据 {size}，建议清理历史"))
    elif total > 50 * 1024 * 1024:
        score -= 7
        hints.append(("info", "应用数据 {size}，偏大但无害"))

    history = int(assets.get("history") or 0)
    limit = max(1, int(assets.get("history_limit") or 240))
    if history > limit * 0.85:
        score -= 10
        hints.append(("warning", "历史 {n} 条，接近上限 {limit}"))

    if expired_trash > 0:
        score -= 5
        hints.append(("info", "回收站 {n} 项过期，可清理"))

    if cache_entries >= 7:
        score -= 3
        hints.append(("info", "分析缓存 {n} 份，占用很少"))

    if not hints:
        hints.append(("success", "未发现问题，状态良好"))

    return {"score": max(5, min(100, score)), "hints": hints[:3]}


def free_backups(root: Path, days: int = 7) -> Tuple[int, int]:
    """删掉 N 天前的 state.json.bak-*，返回 (个数, 字节)。

    只碰应用自己生成的备份文件，其它文件一概不动。
    """
    cutoff = time.time() - days * 86400
    count = 0
    freed = 0
    try:
        entries = list(root.glob("state.json.bak*"))
    except OSError:
        return 0, 0
    for path in entries:
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
    """6px 圆点：分节标题、图例、数据项前面的那一点颜色。"""

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


class Sparkline(QWidget):
    """趋势线：实线 + 极淡的面积填充 + 末端一个亮点。没有渐变。

    点按「距离现在多久」铺在横轴上（x=0 最早，x=1 现在），刚打开时数据少，
    线自然贴在右边慢慢长出来 —— 比把两个点拉满整幅宽、看起来像大幅波动要诚实。
    """

    def __init__(self, token: str = "accent", height: int = 32, parent=None):
        super().__init__(parent)
        self._token = token
        self._points: List[Tuple[float, float]] = []
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_series(self, points: Sequence[Tuple[float, float]]) -> None:
        self._points = [(max(0.0, min(1.0, float(x))), float(v))
                        for x, v in points][-120:]
        self.update()

    def paintEvent(self, _e):
        t = theme()
        col = _q(getattr(t, self._token, t.accent))
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        pad = 3.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # 几条极淡的参考线：数据还没攒够时，空区域也不会像漏画
        p.setPen(QPen(_alpha(t.text, 10), 1.0))
        for frac in (0.25, 0.5, 0.75):
            y = pad + frac * (h - pad * 2)
            p.drawLine(QPointF(pad, y), QPointF(w - pad, y))

        def px(x: float) -> float:
            return pad + x * (w - pad * 2)

        pts = self._points
        if len(pts) < 2:
            pen = QPen(_alpha(t.text, 22), 1.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(pad, h / 2), QPointF(w - pad, h / 2))
            p.end()
            return

        lo = min(v for _x, v in pts)
        hi = max(v for _x, v in pts)
        if hi - lo < 1.0:
            hi = lo + 1.0
        coords = [QPointF(px(x), pad + (1 - (v - lo) / (hi - lo)) * (h - pad * 2))
                  for x, v in pts]
        if pts[-1][0] - pts[0][0] < 0.015:
            # 刚开始采样：两三个点挤在同一列，画线会变成一根竖刺，只点一个点
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(coords[-1], 2.8, 2.8)
            p.end()
            return

        path = QPainterPath(coords[0])
        for pt in coords[1:]:
            path.lineTo(pt)
        area = QPainterPath(path)
        area.lineTo(coords[-1].x(), h)
        area.lineTo(coords[0].x(), h)
        area.closeSubpath()
        p.fillPath(area, _alpha(col, 20))

        pen = QPen(col, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(coords[-1], 2.6, 2.6)
        p.end()


class Ring(QWidget):
    """圆环图：多段占比 + 中心主数字。

    段与段之间留 3° 空隙，圆头端点 —— 比首尾相接的饼图干净得多，
    也不会在深色底上糊成一片。
    """

    def __init__(self, size: int = 128, thickness: int = 12, parent=None):
        super().__init__(parent)
        self._thick = thickness
        self._segs: List[Tuple[float, Any]] = []
        self._center = ""
        self._sub = ""
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_segments(self, segs: Sequence[Tuple[float, Any]],
                     center: str = "", sub: str = "") -> None:
        self._segs = [(float(v), c) for v, c in segs]
        self._center = center
        self._sub = sub
        self.update()

    def paintEvent(self, _e):
        t = theme()
        side = float(min(self.width(), self.height()) - self._thick - 2)
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QPen(_alpha(t.text, 20), self._thick)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawArc(rect, 0, 360 * 16)

        segs = [(v, c) for v, c in self._segs if v > 0]
        total = sum(v for v, _ in segs)
        if total > 0:
            gap = 3.0 if len(segs) > 1 else 0.0
            span_total = 360.0 - gap * len(segs)
            start = -90.0
            for value, color in segs:
                span = span_total * (value / total)
                if span <= 0.2:
                    continue
                pen = QPen(_q(color), self._thick)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rect, int(start * 16), int(span * 16))
                start += span + gap

        inner = max(24.0, side - self._thick * 2 - 6)
        if self._center:
            # 数值可能很长（102.2 MB）：字号按内圈宽度自动收，绝不压到圆环上
            from PyQt6.QtGui import QFontMetricsF

            value_font = font(17.5, QFont.Weight.DemiBold, spacing=-0.3)
            while (value_font.pointSizeF() > 9.0
                   and QFontMetricsF(value_font).horizontalAdvance(self._center) > inner):
                value_font.setPointSizeF(value_font.pointSizeF() - 0.6)
            p.setPen(_q(t.text))
            p.setFont(value_font)
            p.drawText(QRectF(0, rect.center().y() - 16, self.width(), 24),
                       Qt.AlignmentFlag.AlignCenter, self._center)
        if self._sub:
            from PyQt6.QtGui import QFontMetricsF

            sub_font = font(9.6)
            while (sub_font.pointSizeF() > 7.4
                   and QFontMetricsF(sub_font).horizontalAdvance(self._sub) > inner):
                sub_font.setPointSizeF(sub_font.pointSizeF() - 0.4)
            p.setPen(_q(t.text_faint))
            p.setFont(sub_font)
            p.drawText(QRectF(0, rect.center().y() + 6, self.width(), 18),
                       Qt.AlignmentFlag.AlignCenter, self._sub)
        p.end()


class StackBar(QWidget):
    """一条把所有类别串起来的占比条，段间留 2px 空隙。"""

    def __init__(self, height: int = 9, parent=None):
        super().__init__(parent)
        self._segs: List[Tuple[float, Any]] = []
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_segments(self, segs: Sequence[Tuple[float, Any]]) -> None:
        self._segs = [(max(0.0, float(v)), c) for v, c in segs]
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(t.text, 18))
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


class BarRow(QWidget):
    """一行数据：左边颜色点 + 名称，右边数值，下面一条占比细条。"""

    def __init__(self, name: str, token: str = "accent", height: int = 38,
                 mono_value: bool = True, parent=None):
        super().__init__(parent)
        self._name = name
        self._token = token
        self._value = "—"
        self._fraction = 0.0
        self._mono = mono_value
        self.setFixedHeight(height)

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def set_value(self, value: str, fraction: float) -> None:
        self._value = value
        self._fraction = max(0.0, min(1.0, float(fraction)))
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = float(self.width())
        h = float(self.height())
        col = _q(getattr(t, self._token, t.accent))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(2.0, 10.5, 5.0, 5.0))

        p.setPen(_q(t.text_dim))
        p.setFont(font(11.4))
        p.drawText(QRectF(16, 2, max(10.0, w - 168), 22),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   i18n.tr(self._name))

        p.setPen(_q(t.text))
        p.setFont(mono(10.8) if self._mono else font(10.8))
        p.drawText(QRectF(w - 152, 2, 150, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._value)

        bar_y = h - 5
        # 只画有颜色的那一段，不铺满宽度的轨道 —— 铺了整行就像文字被画了下划线
        if self._fraction > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_alpha(col, 200))
            p.drawRoundedRect(QRectF(2, bar_y, max(4.0, (w - 4) * self._fraction), 4), 2, 2)
        p.end()


class MiniStat(QWidget):
    """小方块：一个大数字 + 一个标签 + 一颗彩色点。"""

    def __init__(self, label: str, token: str = "accent", parent=None):
        super().__init__(parent)
        self._label = label
        self._token = token
        self._value = "—"
        self.setFixedHeight(46)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_value(self, value: str) -> None:
        self._value = value
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(_alpha(t.text, 14), 1))
        p.setBrush(_alpha(t.text, 8))
        p.drawRoundedRect(r, 9, 9)

        col = _q(getattr(t, self._token, t.accent))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(11, 12.5, 5, 5))

        p.setPen(_q(t.text))
        p.setFont(font(14.6, QFont.Weight.DemiBold, spacing=-0.2))
        p.drawText(QRectF(22, 5, self.width() - 28, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._value)

        p.setPen(_q(t.text_faint))
        p.setFont(font(9.9))
        p.drawText(QRectF(11, 24, self.width() - 18, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   i18n.tr(self._label))
        p.end()


class HintLine(QWidget):
    """健康提示一行：彩色圆点 + 自动换行的说明。

    用 QLabel 而不是自绘文字，是因为英文提示明显更长，需要真正的自动换行；
    QLabel 的 wordWrap 连行高都能算对，自绘容易把第二行压到第一行上。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        lay.setSpacing(8)
        self.dot = Label("●", 7.6, theme().success)
        self.label = Label("", 10.9, theme().text_dim)
        self.label.setWordWrap(True)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.label, 1)

    def set_hint(self, token: str, text: str) -> None:
        col = getattr(theme(), token, theme().text_dim)
        self.dot.setStyleSheet(f"color: {col}; background: transparent;")
        self.label.setText(text)


class MetricTile(Card):
    """顶部指标卡：标签 + 大数字 + 一行说明 + 可选趋势线。"""

    def __init__(self, caption: str, sub: str = "", with_spark: bool = False,
                 parent=None):
        super().__init__(radius=12, parent=parent)
        self.setFixedHeight(92)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 10, 15, 8)
        lay.setSpacing(1)
        self.caption = Label(caption, 10.3, theme().text_faint)
        self.value = Label("—", 18.5, theme().text,
                           weight=QFont.Weight.DemiBold, spacing=-0.3)
        self.sub = Label(sub, 10.0, theme().text_faint)
        lay.addWidget(self.caption)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)
        self.spark: Optional[Sparkline] = None
        if with_spark:
            self.spark = Sparkline(height=20)
            lay.addWidget(self.spark)
        else:
            lay.addStretch(1)

    def set_value(self, value: str, sub: Optional[str] = None) -> None:
        self.value.setText(value)
        if sub is not None:
            self.sub.setText(sub)


# ------------------------------------------------------------------ 主窗口


class ResourceDialog(GlassDialog):
    """资源管理器窗口。入口在右上角「设置与更多」菜单里。"""

    BLUR_FIXED = True
    REFRESH_MS = 2000

    def __init__(self, store, parent=None, analysis_cache=None,
                 tabs_count: int = 0, on_data_changed=None):
        screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        width = 1080
        height = 800
        if avail is not None:
            width = max(880, min(width, avail.width() - 60))
            height = max(620, min(height, avail.height() - 40))
        super().__init__(parent, width=width, height=height, title="资源管理器")

        self.store = store
        self._cache = analysis_cache
        self._tabs_count = tabs_count
        self._on_data_changed = on_data_changed
        self._samples: deque = deque(maxlen=90)     # (时间戳, 字节)，2s 一个点 = 近 3 分钟
        self._tick_count = 0
        self._last_storage: Dict[str, Any] = {}
        self._last_assets: Dict[str, int] = {}
        self._report_at = 0.0
        self._report_text = ""

        self._build_header_tools()
        self._build()
        self.refresh()

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self._tick)

    # -------------------------------------------------- 构建
    def _build_header_tools(self) -> None:
        lay = self.header.layout()
        if lay is None:
            return
        self.refresh_btn = Button("刷新", "refresh", kind="ghost", height=26,
                                  padding=9, icon_size=12, font_size=11.4, gap=5,
                                  tooltip="重新采集全部指标  ⌘R")
        self.refresh_btn.clicked.connect(self._manual_refresh)
        lay.insertWidget(max(0, lay.count() - 1), self.refresh_btn)

    def _section(self, title: str, sub: str = "") -> Tuple[Card, QVBoxLayout, Label]:
        """统一的分节卡：主题色圆点 + 标题 + 右侧说明 + 内容区。

        返回右侧说明那个 Label，采集到的数值后面直接写进去。
        """
        card = Card(radius=12)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(7)
        head.addWidget(Dot("accent", 5))
        head.addWidget(Label(title, 12.2, theme().text, weight=QFont.Weight.DemiBold))
        head.addStretch(1)
        slot = Label(sub, 10.3, theme().text_faint)
        head.addWidget(slot)
        box.addLayout(head)
        return card, box, slot

    def _build(self) -> None:
        body = QVBoxLayout(self.body)
        body.setContentsMargins(20, 14, 14, 14)
        body.setSpacing(0)

        root = QWidget()
        rv = QVBoxLayout(root)
        rv.setContentsMargins(0, 0, 6, 2)
        rv.setSpacing(12)

        # 顶部四个指标
        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.tile_mem = MetricTile("进程内存", "峰值 —", with_spark=True)
        self.tile_sys = MetricTile("系统内存", "读取中…")
        self.tile_data = MetricTile("应用数据", "读取中…")
        self.tile_rt = MetricTile("运行时", "读取中…")
        for tile in (self.tile_mem, self.tile_sys, self.tile_data, self.tile_rt):
            tiles.addWidget(tile, 1)
        rv.addLayout(tiles)

        rv.addWidget(self._build_actions())

        cols = QHBoxLayout()
        cols.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)
        left.addWidget(self._build_memory())
        left.addWidget(self._build_storage())
        left.addWidget(self._build_disk())
        left.addStretch(1)
        right.addWidget(self._build_health())
        right.addWidget(self._build_assets())
        right.addWidget(self._build_objects())
        right.addStretch(1)
        cols.addLayout(left, 58)
        cols.addLayout(right, 42)
        rv.addLayout(cols)

        scroll = SmoothScrollArea()
        scroll.setWidget(root)
        body.addWidget(scroll)

    def _build_actions(self) -> QWidget:
        card = Card(radius=12)
        card.setFixedHeight(54)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(15, 0, 14, 0)
        lay.setSpacing(8)
        lay.addWidget(Dot("accent", 5))
        lay.addWidget(Label("维护", 12.2, theme().text, weight=QFont.Weight.DemiBold))
        lay.addSpacing(6)

        self.btn_free = Button("释放内存", "broom", kind="primary", height=28,
                               padding=10, icon_size=12, font_size=11.4, gap=6,
                               tooltip="回收 Python 堆 + 图标 / 图片缓存")
        self.btn_cache = Button("清空分析缓存", "spark", height=28, padding=10,
                                icon_size=12, font_size=11.4, gap=6,
                                tooltip="丢掉本轮已生成的 AI 分析结果")
        self.btn_trash = Button("清理过期回收站", "trash", height=28, padding=10,
                                icon_size=12, font_size=11.4, gap=6,
                                tooltip="只清理超过保留天数的条目")
        self.btn_backup = Button("清理旧备份", "download", height=28, padding=10,
                                 icon_size=12, font_size=11.4, gap=6,
                                 tooltip="删除 7 天前的 state.json 自动备份")
        self.btn_free.clicked.connect(self._act_free)
        self.btn_cache.clicked.connect(self._act_cache)
        self.btn_trash.clicked.connect(self._act_trash)
        self.btn_backup.clicked.connect(self._act_backup)
        for btn in (self.btn_free, self.btn_cache, self.btn_trash, self.btn_backup):
            lay.addWidget(btn)

        lay.addStretch(1)
        self.report = Label("", 10.6, theme().text_faint)
        self.report.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.report.setMinimumWidth(180)
        lay.addWidget(self.report)
        return card

    def _build_memory(self) -> QWidget:
        card, box, self.mem_sub = self._section("内存构成")
        row = QHBoxLayout()
        row.setSpacing(18)
        self.mem_ring = Ring(106, 10)
        row.addWidget(self.mem_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        legend = QVBoxLayout()
        legend.setSpacing(2)
        self.mem_rows: Dict[str, BarRow] = {}
        for key, token, name in (
            ("process", "accent", "Ocelot 进程"),
            ("others", "info", "其它应用"),
            ("free", "success", "可用内存"),
        ):
            row_w = BarRow(name, token, height=34)
            self.mem_rows[key] = row_w
            legend.addWidget(row_w)
        legend.addStretch(1)
        row.addLayout(legend, 1)
        box.addLayout(row)

        # 趋势直接长在内存卡里：单独一张卡要多一行标题，800 高的窗口装不下
        self.trend = Sparkline("accent", 36)
        box.addWidget(self.trend)
        self.trend_foot = Label("", 10.2, theme().text_faint, mono_font=True)
        box.addWidget(self.trend_foot)
        return card

    def _build_storage(self) -> QWidget:
        card, box, self.storage_sub = self._section("存储构成")
        self.storage_bar = StackBar(9)
        box.addWidget(self.storage_bar)
        self.storage_rows: Dict[str, BarRow] = {}
        tokens = {"state": "accent", "backup": "info", "log": "warning", "other": "text_faint"}
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for key, token in tokens.items():
            row_w = BarRow(GROUP_META[key], token, height=28)
            self.storage_rows[key] = row_w
            rows.addWidget(row_w)
        box.addLayout(rows)
        return card

    def _build_disk(self) -> QWidget:
        card, box, self.disk_sub = self._section("磁盘")
        self.disk_bar = StackBar(9)
        box.addWidget(self.disk_bar)
        self.disk_card = card          # 数据目录太长了，放悬浮提示里
        return card

    def _build_health(self) -> QWidget:
        card, box, _ = self._section("健康度")
        row = QHBoxLayout()
        row.setSpacing(16)
        self.health_ring = Ring(94, 9)
        row.addWidget(self.health_ring, 0, Qt.AlignmentFlag.AlignVCenter)
        hints = QVBoxLayout()
        hints.setSpacing(4)
        self.health_hints: List[HintLine] = []
        for _ in range(3):
            line = HintLine()
            self.health_hints.append(line)
            hints.addWidget(line)
        hints.addStretch(1)
        row.addLayout(hints, 1)
        box.addLayout(row)
        return card

    def _build_assets(self) -> QWidget:
        card, box, self.assets_sub = self._section("数据资产")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.asset_stats: Dict[str, MiniStat] = {}
        specs = (
            ("requests", "请求数", "accent"),
            ("collections", "集合数", "info"),
            ("history", "历史记录", "success"),
            ("trash", "回收站", "warning"),
            ("environments", "环境数", "danger"),
            ("tabs", "标签页", "text_faint"),
        )
        for i, (key, name, token) in enumerate(specs):
            stat = MiniStat(name, token)
            self.asset_stats[key] = stat
            grid.addWidget(stat, i // 3, i % 3)
        box.addLayout(grid)
        return card

    def _build_objects(self) -> QWidget:
        card, box, self.objects_sub = self._section("对象分布")
        self.object_rows: List[BarRow] = []
        tokens = ("accent", "info", "success", "warning", "danger")
        rows = QVBoxLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for i in range(5):
            row_w = BarRow("—", tokens[i], height=27)
            self.object_rows.append(row_w)
            rows.addWidget(row_w)
        box.addLayout(rows)
        return card

    # -------------------------------------------------- 刷新
    def showEvent(self, e):
        super().showEvent(e)
        if i18n.current() != "en":
            # 英文下 GlassDialog 已经调过 refresh_i18n()，这里不必再来一遍（对象扫描不便宜）
            self.refresh()
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        # ⌘R / Ctrl+R：重采一次全部指标（隐藏时也能用，方便测试）
        if (e.key() == Qt.Key.Key_R
                and e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._manual_refresh()
            return
        super().keyPressEvent(e)

    def done(self, result: int) -> None:
        self._timer.stop()
        # 关窗即丢掉采样，不在后台继续攒数据
        self._samples.clear()
        super().done(result)

    def _manual_refresh(self) -> None:
        self.refresh()
        self.refresh_btn.spin_once(520)
        self._flash_report("指标已刷新", "info")

    def refresh(self) -> None:
        self._refresh_memory()
        self._refresh_storage()
        self._refresh_assets()
        self._refresh_objects()
        self._refresh_health()

    def _tick(self) -> None:
        self._tick_count += 1
        self._refresh_memory()
        # 存储 / 对象这类扫描不必每 2 秒来一次，12 秒一次足够
        if self._tick_count % 6 == 0:
            self._refresh_storage()
            self._refresh_assets()
            self._refresh_health()

    def _refresh_memory(self) -> None:
        try:
            proc = process_memory()
            sysmem = system_memory()
        except Exception:  # noqa: BLE001
            return
        rss = proc["rss"]
        if rss:
            self._samples.append((time.time(), float(rss)))
            if self.tile_mem.spark is not None:
                self.tile_mem.spark.set_series(self._series())

        self.tile_mem.set_value(
            human_bytes(rss) if rss else "—",
            i18n.trf("峰值 {v}", v=human_bytes(proc["peak"])))

        total = sysmem["total"]
        avail = sysmem["available"]
        pct = sysmem["percent"]
        if total:
            self.tile_sys.set_value(
                f"{pct:.0f}%",
                i18n.trf("已用 {used} / {total}",
                         used=human_bytes(sysmem["used"]), total=human_bytes(total)))
        else:
            self.tile_sys.set_value("—", i18n.tr("无法读取系统内存"))

        # 环形图：进程 / 其它应用 / 可用
        used = sysmem["used"] or rss
        others = max(0, used - rss)
        segs = [(rss, theme().accent), (others, theme().info), (avail, theme().success)]
        self.mem_ring.set_segments(segs, human_bytes(rss) if rss else "—", "Ocelot")

        base = total or (used + avail) or 1
        self.mem_sub.setText(i18n.trf("整机 {total}", total=human_bytes(total) if total else "—"))
        for key, value in (("process", rss), ("others", others), ("free", avail)):
            self.mem_rows[key].set_value(
                f"{human_bytes(value)} · {value / base * 100:.0f}%",
                value / base if base else 0.0)

        self._refresh_trend(rss)

    def _series(self) -> List[Tuple[float, float]]:
        """(x=0 最早 ~ 1 现在, 字节)：按真实时间铺开，刚开始只占右边一小段。"""
        now = time.time()
        window = SAMPLE_WINDOW
        out: List[Tuple[float, float]] = []
        for ts, value in self._samples:
            x = 1.0 - (now - ts) / window
            if x >= 0:
                out.append((x, value))
        return out

    def _refresh_trend(self, rss: int) -> None:
        vals = [v for _, v in self._samples if v > 0]
        self.trend.set_series(self._series())
        if vals:
            lo, hi = min(vals), max(vals)
            avg = sum(vals) / len(vals)
            span = (self._samples[-1][0] - self._samples[0][0]) if len(self._samples) > 1 else 0
            head = (i18n.trf("近 {m} 分钟", m=max(1, round(span / 60)))
                    if span >= 60 else i18n.tr("刚开始采样"))
            self.trend_foot.setText(head + i18n.trf(
                " · 现在 {now} · 最低 {lo} · 平均 {avg} · 最高 {hi}",
                now=human_bytes(rss), lo=human_bytes(lo),
                avg=human_bytes(avg), hi=human_bytes(hi)))
        else:
            self.trend_foot.setText(i18n.tr("采样中…"))

    def _refresh_storage(self) -> None:
        try:
            from .store import APP_DIR

            data = storage_scan(APP_DIR)
        except Exception:  # noqa: BLE001
            return
        self._last_storage = data
        total = data["total"]
        self.tile_data.set_value(
            human_bytes(total),
            i18n.trf("{files} 个文件 · 状态 {state}",
                     files=data["files"],
                     state=human_bytes(next((g["size"] for g in data["groups"]
                                             if g["key"] == "state"), 0))))
        self.storage_sub.setText(i18n.trf("应用数据 {size}", size=human_bytes(total)))
        colors = {"state": theme().accent, "backup": theme().info,
                  "log": theme().warning, "other": theme().text_faint}
        base = total or 1
        self.storage_bar.set_segments([(g["size"], colors[g["key"]]) for g in data["groups"]])
        for g in data["groups"]:
            row = self.storage_rows[g["key"]]
            row.set_value(human_bytes(g["size"]), g["size"] / base if total else 0.0)
            row.setToolTip(i18n.trf("{n} 个文件", n=g["files"]))
        disk = data["disk"]
        if disk["total"]:
            free_pct = disk["free"] / disk["total"] * 100
            self.disk_sub.setText(i18n.trf("剩余 {free}（{pct}%）",
                                           free=human_bytes(disk["free"]),
                                           pct=f"{free_pct:.0f}"))
            self.disk_bar.set_segments([(disk["used"], theme().accent),
                                        (disk["free"], _alpha(theme().text, 45))])
            self.disk_card.setToolTip(i18n.trf(
                "已用 {used} · 可用 {free}\n数据目录 {path}",
                used=human_bytes(disk["used"]), free=human_bytes(disk["free"]),
                path=data["root"]))
        else:
            self.disk_sub.setText("")
            self.disk_bar.set_segments([])
            self.disk_card.setToolTip(data["root"])

    def _refresh_assets(self) -> None:
        try:
            assets = data_assets(self.store, self._tabs_count)
        except Exception:  # noqa: BLE001
            return
        self._last_assets = assets
        for key, stat in self.asset_stats.items():
            stat.set_value(human_count(assets.get(key, 0)))
        self.assets_sub.setText(i18n.trf("共 {n} 个请求",
                                         n=human_count(assets.get("requests", 0))))

    def _refresh_objects(self) -> None:
        try:
            stats = object_stats(5)
            runtime = runtime_stats()
        except Exception:  # noqa: BLE001
            return
        top = stats["top"]
        peak = max((n for _name, n in top), default=1) or 1
        for i, row_w in enumerate(self.object_rows):
            if i < len(top):
                name, count = top[i]
                row_w.show()
                row_w.set_name(name)
                row_w.set_value(human_count(count), count / peak)
            else:
                row_w.hide()
        self.objects_sub.setText(i18n.trf("{n} 个对象 · {k} 种类型",
                                          n=human_count(stats["total"]),
                                          k=human_count(stats["types"])))
        self.tile_rt.set_value(
            human_count(stats["total"]),
            i18n.trf("线程 {t} · 控件 {w} · 缓存 {c}",
                     t=runtime["threads"], w=runtime["widgets"],
                     c=len(self._cache) if self._cache is not None else 0))

    def _refresh_health(self) -> None:
        try:
            from .store import APP_DIR

            mem = system_memory()
            storage = self._last_storage or storage_scan(APP_DIR)
            assets = self._last_assets or data_assets(self.store, self._tabs_count)
            expired = sum(1 for r in (self.store.trash or [])
                          if float(r.get("deleted_at", 0)) <
                          time.time() - self.store.trash_keep_days() * 86400)
        except Exception:  # noqa: BLE001
            return
        status = health_status(
            mem, storage, assets,
            cache_entries=len(self._cache) if self._cache is not None else 0,
            expired_trash=expired)
        score = status["score"]
        token = "success" if score >= 85 else ("warning" if score >= 65 else "danger")
        self.health_ring.set_segments(
            [(score, getattr(theme(), token))], str(score), i18n.tr("健康分"))
        metrics = {"pct": f"{mem['percent']:.0f}", "size": human_bytes(storage.get("total", 0)),
                   "n": human_count(assets.get("history", 0)),
                   "limit": human_count(assets.get("history_limit", 240))}
        expired_n = {"n": human_count(expired)}
        for i, line in enumerate(self.health_hints):
            if i < len(status["hints"]):
                level, tpl = status["hints"][i]
                args = dict(metrics)
                args.update(expired_n)
                text = i18n.trf(tpl, **args) if "{" in tpl else i18n.tr(tpl)
                line.set_hint(level, text)
                line.show()
            else:
                line.hide()

    # -------------------------------------------------- 维护动作
    def _flash_report(self, text: str, token: str = "success") -> None:
        self._report_text = text
        self._report_at = time.time()
        self.report.setText(text)
        col = {"success": theme().success, "info": theme().text_dim,
               "warning": theme().warning, "danger": theme().danger}.get(token, theme().text_dim)
        self.report.setStyleSheet(f"color: {col}; background: transparent;")
        fade_in(self.report, 200)

    def _act_free(self) -> None:
        before = process_memory()["rss"]
        self.btn_free.set_busy(True)
        try:
            from . import icons

            entries = icons.clear_cache()
            gc.collect()
            gc.collect()
            if sys.platform.startswith("linux"):
                try:
                    import ctypes

                    ctypes.CDLL("libc.so.6").malloc_trim(0)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            entries = 0

        def finish() -> None:
            self.btn_free.set_busy(False)
            self.btn_free.spin_once(520)
            after = process_memory()["rss"]
            freed = before - after
            self.refresh()
            if freed > 256 * 1024:
                self._flash_report(i18n.trf("已释放 {v}", v=human_bytes(freed)), "success")
            elif entries:
                self._flash_report(i18n.trf("已整理堆内存，回收 {n} 个缓存条目",
                                            n=human_count(entries)), "success")
            else:
                self._flash_report(i18n.tr("内存已经很干净，无需释放"), "info")

        QTimer.singleShot(360, finish)

    def _act_cache(self) -> None:
        if self._cache is None:
            self._flash_report(i18n.tr("没有可清理的分析缓存"), "info")
            return
        n = len(self._cache)
        self._cache.clear()
        self.btn_cache.spin_once(520)
        self._refresh_objects()
        if n:
            self._flash_report(i18n.trf("已清空 {n} 份分析缓存", n=n), "success")
        else:
            self._flash_report(i18n.tr("分析缓存本来就是空的"), "info")

    def _act_trash(self) -> None:
        try:
            n = self.store.purge_expired_trash()
            if n:
                self.store.save()
                self._notify_data_changed()
        except Exception:  # noqa: BLE001
            n = 0
        self.btn_trash.spin_once(520)
        self.refresh()
        if n:
            self._flash_report(i18n.trf("已清理 {n} 项过期记录", n=n), "success")
        else:
            self._flash_report(i18n.tr("没有过期的回收站条目"), "info")

    def _act_backup(self) -> None:
        try:
            from .store import APP_DIR

            count, freed = free_backups(APP_DIR)
        except Exception:  # noqa: BLE001
            count, freed = 0, 0
        self.btn_backup.spin_once(520)
        self._refresh_storage()
        self._refresh_health()
        if count:
            self._flash_report(i18n.trf("已删除 {n} 个旧备份 · {v}",
                                       n=count, v=human_bytes(freed)), "success")
        else:
            self._flash_report(i18n.tr("没有超过 7 天的备份"), "info")

    def _notify_data_changed(self) -> None:
        if callable(self._on_data_changed):
            try:
                self._on_data_changed()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------- 语言
    def refresh_i18n(self) -> None:
        """语言切换后重设动态文案（采集值本身不需要翻译）。"""
        self._refresh_memory()
        self._refresh_storage()
        self._refresh_assets()
        self._refresh_objects()
        self._refresh_health()
