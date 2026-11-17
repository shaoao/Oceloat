"""集合运行器：按顺序把一个文件夹里的请求跑一遍，汇总状态 / 耗时 / 体积。

设计要点：
- 顺序执行（不并发），避免把被测服务打爆，也方便看「哪一条变慢了」；
- 每条请求保留完整响应，跑完点进去就能直接看这一条的结果；
- 复用 ApiClient，代理 / 节点 / 超时 / 环境变量与手动发送完全一致；
- 运行过程中可随时停止，已跑完的结果保留。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter
from PyQt6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

from .code_editor import human_elapsed, human_size
from .dialogs import GlassDialog
from .http_client import ApiClient, Response
from .i18n import tr
from .theme import C, font, method_color, mono, status_color, theme
from .widgets import Button, Card, HBox, Label

ROW_H = 38


def flatten_requests(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    """深度优先收集文件夹下的全部请求，保持树的顺序。"""
    out: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = [node]
    while stack:
        cur = stack.pop()
        if cur.get("type") == "request":
            out.append(cur)
        else:
            kids = cur.get("children") or []
            stack.extend(reversed(kids))
    return out


# ---------------------------------------------------------------- 引擎


class CollectionRunner(QObject):
    """顺序跑完一组请求。信号：started(总数) / progress(下标, 记录) / done(记录列表)。"""

    started = pyqtSignal(int)
    progress = pyqtSignal(int, object)
    done = pyqtSignal(list)

    def __init__(self, store, requests: List[Dict[str, Any]], parent=None):
        super().__init__(parent)
        self.store = store
        self.requests = list(requests)
        self.client = ApiClient(self)
        self.client.finished.connect(self._on_finished)
        self._index = -1
        self._inflight = False
        self._running = False
        self._stopped = False
        self.records: List[Dict[str, Any]] = []

    # -------------------------------------------------- 控制
    def start(self) -> None:
        if self._running:
            return
        self.records = []
        self._index = -1
        self._running = True
        self._stopped = False
        self.started.emit(len(self.requests))
        QTimer.singleShot(0, self._next)

    def stop(self) -> None:
        self._stopped = True
        self._running = False
        self.client.abort()

    @property
    def running(self) -> bool:
        return self._running

    # -------------------------------------------------- 内部
    def _settings(self) -> Dict[str, Any]:
        settings = dict(self.store.settings)
        settings.pop("relay_node", None)
        settings["node_proxy"] = ""
        return settings

    def _next(self) -> None:
        if not self._running or self._stopped:
            self._finish()
            return
        self._index += 1
        if self._index >= len(self.requests):
            self._finish()
            return
        req = self.requests[self._index]
        self._inflight = True
        self._t0 = time.perf_counter()
        self.client.send(req, self._settings(), self.store.env_vars())
        # send() 在地址为空等情况下会同步发 finished，_on_finished 已经接管后续调度

    def _on_finished(self, resp: Response) -> None:
        if not self._inflight:
            return
        self._inflight = False
        req = self.requests[self._index] if 0 <= self._index < len(self.requests) else {}
        elapsed = resp.elapsed or int((time.perf_counter() - self._t0) * 1000)
        rec = {
            "index": self._index,
            "name": req.get("name") or "Untitled Request",
            "method": req.get("method", "GET"),
            "url": resp.url or req.get("url", ""),
            "status": resp.status,
            "reason": resp.reason,
            "elapsed": elapsed,
            "size": resp.size or len(resp.body or b""),
            "ok": (not resp.error) and resp.ok,
            "error": resp.error,
            "request": req,
            # 完整响应留下来：点这一行就能查看本次运行这一条的结果
            "response": resp,
        }
        self.records.append(rec)
        self.progress.emit(rec["index"], rec)
        if not self._running or self._stopped:
            self._finish()
            return
        QTimer.singleShot(20, self._next)

    def _finish(self) -> None:
        if not self._running and not self._stopped:
            return
        self._running = False
        self.done.emit(list(self.records))


# ---------------------------------------------------------------- 行


class RunRow(QWidget):
    clicked = pyqtSignal(dict)

    def __init__(self, index: int, request: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.index = index
        self.request = request
        self.rec: Optional[Dict[str, Any]] = None
        self.state = "pending"          # pending / running / done
        self._hover = False
        self.setFixedHeight(ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -------------------------------------------------- 状态
    def set_running(self) -> None:
        self.state = "running"
        self.update()

    def set_record(self, rec: Dict[str, Any]) -> None:
        self.rec = rec
        self.state = "done"
        self.update()

    def reset(self) -> None:
        self.rec = None
        self.state = "pending"
        self.update()

    # -------------------------------------------------- 交互
    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            # 带上本次运行的记录：跑完的条目点进去能直接看到那一次的响应。
            payload = dict(self.rec or {})
            payload.setdefault("request", self.request)
            self.clicked.emit(payload)
        super().mouseReleaseEvent(e)

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            # 用主题自带的极淡 hover（深色约 14/255），不要覆写 alpha，
            # 之前 150 的灰度在暗底上像选中的亮条，太扎眼。
            p.setBrush(QColor(C(t.hover)))
            p.drawRoundedRect(QRectF(4, 2, w - 8, h - 4), 7, 7)

        rec = self.rec or {}
        w = float(w)

        # 全部按「基线点」绘制：QRectF + 对齐标志在部分 DPI 下会自己做一次取整，
        # 不同字宽（GET / DELETE）会呈现出忽左忽右的错觉，这里统一算死坐标。
        def baseline(painter, f):
            fm = QFontMetricsF(f)
            return fm, h / 2 + (fm.ascent() - fm.descent()) / 2

        def text_right(painter, fm, right_x, y, txt, color):
            painter.setPen(color)
            painter.drawText(QPointF(right_x - fm.horizontalAdvance(txt), y), txt)

        method = (self.request.get("method") or "GET").upper()
        mc = QColor(method_color(method, t))
        if self.state == "pending":
            mc.setAlpha(150 if t.is_dark else 190)
        mf = mono(10, spacing=0.3)
        mf.setBold(True)
        p.setFont(mf)
        _fm, y = baseline(p, mf)
        p.setPen(mc)
        p.drawText(QPointF(14, y), method)

        name = self.request.get("name") or "Untitled Request"
        nf = font(12)
        p.setFont(nf)
        nfm = QFontMetricsF(nf)
        y_name = h / 2 + (nfm.ascent() - nfm.descent()) / 2
        avail = max(60.0, w - 74 - 214)
        p.setPen(QColor(t.text if self.state != "pending" else t.text_dim))
        p.drawText(QPointF(72, y_name), nfm.elidedText(name, Qt.TextElideMode.ElideRight, avail))

        # 右侧三列：状态 / 耗时 / 体积
        right = w - 14
        sf = mono(10.5)
        p.setFont(sf)
        sfm, ys = baseline(p, sf)

        size_txt = human_size(int(rec.get("size") or 0)) if self.state == "done" else "—"
        text_right(p, sfm, right, ys, size_txt, QColor(t.text_faint))

        time_txt = human_elapsed(int(rec.get("elapsed") or 0)) if self.state == "done" else "—"
        text_right(p, sfm, right - 74, ys, time_txt, QColor(t.text_dim))

        status_right = right - 152
        if self.state == "running":
            bf = font(11)
            p.setFont(bf)
            bfm, yb = baseline(p, bf)
            text_right(p, bfm, status_right, yb, tr("运行中"), QColor(t.text_faint))
        elif self.state == "done":
            if rec.get("error"):
                color = QColor(t.danger)
                label = tr("失败")
            else:
                color = QColor(status_color(int(rec.get("status") or 0), t))
                label = str(rec.get("status") or 0)
            text_right(p, sfm, status_right, ys, label, color)

            # 左侧一条状态条，扫一眼就知道哪条挂了
            p.setPen(Qt.PenStyle.NoPen)
            strip = QColor(color)
            strip.setAlpha(210)
            p.setBrush(strip)
            p.drawRoundedRect(QRectF(3, 8, 2.5, h - 16), 1.2, 1.2)
        else:
            text_right(p, sfm, status_right, ys, tr("待运行"), QColor(t.text_faint))
        p.end()


# ---------------------------------------------------------------- 对话框


class RunnerDialog(GlassDialog):
    """运行集合：逐条跑、实时更新，点某一行可以直接打开那条请求。"""

    openRequested = pyqtSignal(dict)

    def __init__(self, store, folder: Dict[str, Any], parent=None):
        requests = flatten_requests(folder)
        super().__init__(parent, 760, 580, tr("运行集合"))
        self.store = store
        self.folder = folder
        self.requests = requests
        self.rows: List[RunRow] = []
        self.runner: Optional[CollectionRunner] = None
        self._done = False

        body = QVBoxLayout(self.body)
        body.setContentsMargins(16, 10, 16, 14)
        body.setSpacing(10)

        self.scope = Label(f"{folder.get('name') or 'Collection'} · "
                           f"{len(requests)} {tr('个请求')}", 12, theme().text_dim)
        self.counter = Label(f"0 / {len(requests)}", 11.5, theme().text_faint)
        self.counter.setFont(mono(11))
        self.summ = Label("", 11.5, theme().text_faint)
        self.run_btn = Button(tr("开始运行"), "play", kind="primary", height=28,
                              padding=14, font_size=12)
        self.run_btn.clicked.connect(self._toggle)
        self.copy_btn = Button(tr("复制结果"), "copy", kind="subtle", height=28,
                               padding=10, font_size=12)
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setEnabled(False)
        body.addWidget(HBox(self.scope, 1, self.counter, self.copy_btn, self.run_btn, spacing=8))

        card = Card(radius=9)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(2, 4, 2, 4)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.rows_box = QVBoxLayout(holder)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(0)
        for i, req in enumerate(requests):
            row = RunRow(i, req)
            row.clicked.connect(self._open_request)
            self.rows.append(row)
            self.rows_box.addWidget(row)
        if not requests:
            empty = Label(tr("这个文件夹里还没有请求"), 12, theme().text_faint)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setFixedHeight(120)
            self.rows_box.addWidget(empty)
        self.rows_box.addStretch(1)
        self.scroll.setWidget(holder)
        cl.addWidget(self.scroll)
        body.addWidget(card, 1)
        body.addWidget(HBox(self.summ, 1))

        self.run_btn.setEnabled(bool(requests))

    # -------------------------------------------------- 运行
    def _toggle(self) -> None:
        if self.runner and self.runner.running:
            self.runner.stop()
            self.run_btn.setText(tr("重新运行"))
            self.run_btn.setEnabled(True)
            return
        self._start()

    def _start(self) -> None:
        for row in self.rows:
            row.reset()
        self._done = False
        self.summ.setText("")
        self.copy_btn.setEnabled(False)
        self.counter.setText(f"0 / {len(self.requests)}")
        self.run_btn.setText(tr("停止"))
        self.runner = CollectionRunner(self.store, self.requests, self)
        self.runner.started.connect(lambda _n: None)
        self.runner.progress.connect(self._on_progress)
        self.runner.done.connect(self._on_done)
        self.runner.start()
        self._mark_running(0)

    def _mark_running(self, i: int) -> None:
        for row in self.rows:
            if row.state == "running":
                row.state = "pending"
                row.update()
        if 0 <= i < len(self.rows):
            self.rows[i].set_running()
            self._scroll_to(i)

    def _scroll_to(self, i: int) -> None:
        if 0 <= i < len(self.rows):
            self.scroll.ensureWidgetVisible(self.rows[i], 0, ROW_H)

    def _on_progress(self, index: int, rec: Dict[str, Any]) -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_record(rec)
        self.counter.setText(f"{index + 1} / {len(self.requests)}")
        self._mark_running(index + 1)

    def _on_done(self, records: List[Dict[str, Any]]) -> None:
        self._done = True
        self.run_btn.setText(tr("再跑一次"))
        self.run_btn.setEnabled(True)
        for row in self.rows:
            if row.state == "running":
                row.state = "pending"
                row.update()
        ok = sum(1 for r in records if r.get("ok"))
        bad = len(records) - ok
        total = sum(int(r.get("elapsed") or 0) for r in records)
        t = theme()
        self.counter.setText(f"{len(records)} / {len(self.requests)}")
        self.summ.setText(f"{tr('成功')} {ok} · {tr('失败')} {bad} · {tr('总耗时')} {human_elapsed(total)}")
        self.summ.setStyleSheet(f"color: {t.danger if bad else t.text_dim};")
        self.copy_btn.setEnabled(bool(records))

    # -------------------------------------------------- 结果操作
    def _open_request(self, payload: Dict[str, Any]) -> None:
        self.openRequested.emit(payload)

    def _copy(self) -> None:
        if not self.runner:
            return
        lines = ["name\tmethod\tstatus\telapsed_ms\tsize\turl"]
        for r in self.runner.records:
            lines.append("\t".join([
                str(r.get("name", "")), str(r.get("method", "")),
                str(r.get("status", 0)), str(r.get("elapsed", 0)),
                str(r.get("size", 0)), str(r.get("url", "")),
            ]))
        QApplication.clipboard().setText("\n".join(lines))

    def closeEvent(self, e):  # noqa: N802
        if self.runner and self.runner.running:
            self.runner.stop()
        super().closeEvent(e)

    def reject(self) -> None:
        if self.runner and self.runner.running:
            self.runner.stop()
        super().reject()
