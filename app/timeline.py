"""响应时间线：同一个地址最近若干次的耗时与状态，一眼看出「什么时候开始变慢」。

数据直接来自历史记录（store.history），不额外存任何东西：
- 每根柱子是一次请求，高度是耗时，颜色是状态码；
- 悬停显示那一次的时间、状态码与耗时；
- 顶部一行统计：次数 / 成功率 / 平均 / P95 / 最慢。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .theme import C, font, mono, status_color, theme

PAD_L, PAD_R, PAD_T, PAD_B = 44, 16, 74, 26


class TimelineView(QWidget):
    """耗时柱状图 + 统计头。条目按时间从旧到新。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: List[Dict[str, Any]] = []
        self._hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(220)

    # -------------------------------------------------- 数据
    def set_entries(self, entries: List[Dict[str, Any]]) -> None:
        self.entries = list(entries or [])
        self._hover = -1
        self.update()

    def _stats(self) -> Dict[str, Any]:
        rows = [e for e in self.entries]
        if not rows:
            return {"n": 0}
        times = sorted(int(e.get("elapsed") or 0) for e in rows)
        ok = sum(1 for e in rows if 200 <= int(e.get("status") or 0) < 400)
        p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
        return {
            "n": len(rows), "ok": ok,
            "avg": sum(times) / len(times),
            "p95": p95, "max": times[-1], "min": times[0],
        }

    # -------------------------------------------------- 交互
    def mouseMoveEvent(self, e):
        idx = self._index_at(e.position().x())
        if idx != self._hover:
            self._hover = idx
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def _plot_rect(self) -> QRectF:
        return QRectF(PAD_L, PAD_T, max(self.width() - PAD_L - PAD_R, 10),
                      max(self.height() - PAD_T - PAD_B, 10))

    def _index_at(self, x: float) -> int:
        if not self.entries:
            return -1
        r = self._plot_rect()
        if x < r.left() or x > r.right():
            return -1
        step = r.width() / len(self.entries)
        idx = int((x - r.left()) / step)
        return max(0, min(len(self.entries) - 1, idx))

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        stats = self._stats()
        if not stats["n"]:
            self._paint_empty(p)
            p.end()
            return

        # ---------- 统计头
        self._paint_stats(p, stats)

        r = self._plot_rect()
        # 基线
        p.setPen(QPen(C(t.border), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))

        top = max(int(stats["max"]), 1)
        n = len(self.entries)
        step = r.width() / n
        bar_w = max(3.0, min(step * 0.62, 22.0))

        for i, entry in enumerate(self.entries):
            elapsed = int(entry.get("elapsed") or 0)
            status = int(entry.get("status") or 0)
            h = max(2.0, r.height() * (elapsed / top))
            x = r.left() + step * i + (step - bar_w) / 2
            col = QColor(status_color(status, t))
            if i == self._hover:
                col = col.lighter(118) if t.is_dark else col.darker(108)
            else:
                col.setAlpha(190 if i == n - 1 else 150)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, r.bottom() - h, bar_w, h), min(3, bar_w / 2),
                              min(3, bar_w / 2))

        # Y 轴刻度：0 / 中值 / 峰值
        p.setFont(mono(9.2))
        p.setPen(C(t.text_faint))
        for frac in (0.0, 0.5, 1.0):
            val = int(top * frac)
            y = r.bottom() - r.height() * frac
            txt = f"{val}ms"
            fm = QFontMetricsF(mono(9.2))
            p.drawText(QPointF(r.left() - 8 - fm.horizontalAdvance(txt), y + 3.5), txt)

        # X 轴：最早 / 最近
        p.setFont(mono(9.2))
        if n >= 2:
            first = time.strftime("%H:%M", time.localtime(self.entries[0].get("ts") or 0))
            last = time.strftime("%H:%M", time.localtime(self.entries[-1].get("ts") or 0))
            p.drawText(QPointF(r.left(), r.bottom() + 16), first)
            fm = QFontMetricsF(mono(9.2))
            p.drawText(QPointF(r.right() - fm.horizontalAdvance(last), r.bottom() + 16), last)

        # ---------- 悬停详情
        if 0 <= self._hover < n:
            self._paint_hover(p, self.entries[self._hover], r, step, top)
        p.end()

    def _paint_empty(self, p: QPainter) -> None:
        t = theme()
        p.setFont(font(12.5))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(0, 0, self.width(), self.height()),
                   int(Qt.AlignmentFlag.AlignCenter),
                   "这个地址还没有足够的历史记录\n再发几次，就能看到耗时趋势了")

    def _paint_stats(self, p: QPainter, stats: Dict[str, Any]) -> None:
        t = theme()
        items = [
            ("次数", str(stats["n"]), t.text),
            ("成功率", f"{stats['ok'] / stats['n'] * 100:.0f}%",
             t.text if stats["ok"] == stats["n"] else t.warning),
            ("平均", f"{stats['avg']:.0f}ms", t.text_dim),
            ("P95", f"{stats['p95']}ms", t.text_dim),
            ("最慢", f"{stats['max']}ms",
             t.danger if stats["max"] > stats["avg"] * 3 else t.text_dim),
        ]
        x = 16.0
        for label, value, color in items:
            p.setFont(font(9.6))
            fm = QFontMetricsF(font(9.6))
            p.setPen(C(t.text_faint))
            p.drawText(QPointF(x, 26), label)
            p.setFont(mono(13.2))
            vf = mono(13.2)
            vf.setBold(True)
            p.setFont(vf)
            p.setPen(C(color))
            p.drawText(QPointF(x, 48), value)
            x += max(fm.horizontalAdvance(label), QFontMetricsF(vf).horizontalAdvance(value)) + 26

    def _paint_hover(self, p: QPainter, entry: Dict[str, Any], r: QRectF,
                     step: float, top: int) -> None:
        t = theme()
        idx = self._hover
        elapsed = int(entry.get("elapsed") or 0)
        status = int(entry.get("status") or 0)
        x = r.left() + step * idx + step / 2
        p.setPen(QPen(C(t.border_strong), 1, Qt.PenStyle.DotLine))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

        ts = time.strftime("%m-%d %H:%M:%S", time.localtime(entry.get("ts") or 0))
        lines = [f"{ts}", f"{status} · {elapsed}ms"]
        f = mono(10)
        fm = QFontMetricsF(f)
        w = max(fm.horizontalAdvance(s) for s in lines) + 20
        h = 40.0
        bx = min(max(x + 10, r.left()), r.right() - w)
        by = r.top() - 4
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(QRectF(bx, by, w, h), 7, 7)
        p.setFont(f)
        p.setPen(C(t.text))
        p.drawText(QPointF(bx + 10, by + 15), lines[0])
        p.setPen(C(status_color(status, t)))
        p.drawText(QPointF(bx + 10, by + 31), lines[1])
