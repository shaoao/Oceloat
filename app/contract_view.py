"""契约页：左边契约 / 漂移，右边观测，中间可拖动。

数据仍来自 app.contract；这一页只做展示与交互。布局比例存在
store.settings["contract_split"]，绝不写进 contracts 数据，保证契约数据完整。
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout, QSplitter, QSplitterHandle, QTextBrowser, QVBoxLayout, QWidget,
)

from . import contract, i18n
from .code_editor import CodeView
from .theme import C, S, font, mono, theme
from .widgets import Button, Divider, ElideLabel, HBox, Label, SegmentedTabs


class _Handle(QSplitterHandle):
    """1px 细线 + 8px 拖拽热区，不用彩色描边。"""

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        t = theme()
        p.fillRect(self.rect(), C(t.window))
        if self.orientation() == Qt.Orientation.Horizontal:
            x = self.width() // 2
            p.fillRect(x, 4, 1, max(0, self.height() - 8), C(t.border_strong))
        else:
            y = self.height() // 2
            p.fillRect(4, y, max(0, self.width() - 8), 1, C(t.border_strong))


class _Splitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:
        return _Handle(self.orientation(), self)


class _Metric(QWidget):
    """一行指标：左侧小字说明，右侧主题色数值，窄了自动省略。"""

    def __init__(self, caption: str, value: str = "—", accent: bool = False,
                 parent=None):
        super().__init__(parent)
        self._accent = accent
        self.caption = Label(caption, 10.2, theme().text_faint)
        self.value = ElideLabel(
            value, 11.8, theme().accent if accent else theme().text,
            weight=font(11.8).weight(), mono_font=True)
        self.value.setObjectName("metric_value")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.caption, 0)
        lay.addWidget(self.value, 1)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class _Bar(QWidget):
    """单条耗时：实心主题色 / 估算灰白，没有渐变。"""

    def __init__(self, measured: bool, parent=None):
        super().__init__(parent)
        self._measured = measured
        self._ratio = 0.0
        self.setFixedHeight(5)
        self.setMinimumWidth(30)

    def set_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, float(ratio or 0)))
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        t = theme()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.selected))
        p.drawRoundedRect(self.rect(), 2, 2)
        if self._ratio <= 0:
            return
        width = max(2, int(self.width() * self._ratio))
        p.setBrush(C(t.accent if self._measured else t.text_dim))
        p.drawRoundedRect(0, 0, width, self.height(), 2, 2)


class _TimingRow(QWidget):
    def __init__(self, label: str, measured: bool, parent=None):
        super().__init__(parent)
        self.bar = _Bar(measured)
        self.value = Label("—", 10.8, theme().accent if measured else theme().text_dim,
                           mono_font=True)
        self.value.setFixedWidth(62)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        lay.addWidget(Label(label, 10.6, theme().text_faint, mono_font=True), 0)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.value, 0)

    def set_value(self, ms: int) -> None:
        self.value.setText(f"{ms} ms")


class ContractView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self._key = ""
        self._body = b""
        self._content_type = ""
        self._timing: Dict[str, int] = {}
        self._meta: Dict[str, Any] = {}
        self._issues: List[str] = []
        self._restoring = False

        # ---- 顶部动作行：状态可省略，按钮等高等距排右侧
        self.status = ElideLabel("", 11.2, theme().text_dim, mode=Qt.TextElideMode.ElideRight)
        self.save_btn = Button("保存为契约", "plus", kind="subtle", height=24,
                               padding=8, font_size=11.2,
                               tooltip="把当前响应结构保存为该接口的基准契约")
        self.check_btn = Button("检查漂移", "refresh", kind="ghost", height=24,
                                padding=8, font_size=11.2,
                                tooltip="用已保存的契约比对当前响应字段")
        self.clear_btn = Button("删除契约", "trash", kind="ghost", height=24,
                                padding=8, font_size=11.2)
        self.copy_btn = Button("复制 Schema", "copy", kind="ghost", height=24,
                               padding=8, font_size=11.2)
        self.save_btn.clicked.connect(self._save)
        self.check_btn.clicked.connect(self._check)
        self.clear_btn.clicked.connect(self._clear)
        self.copy_btn.clicked.connect(self._copy_schema)
        actions = HBox(self.status, 1, self.save_btn, self.check_btn,
                       self.clear_btn, self.copy_btn, spacing=6)

        self.filter = SegmentedTabs(
            [("all", "全部"), ("missing", "字段消失"),
             ("new", "新增字段"), ("type", "类型变化")],
            style="pill", height=23, font_size=10.5, pad_h=8)
        self.filter.set_current("all", emit=False)
        self.filter.changed.connect(lambda _k: self._render_drift())

        # ---- 左栏：三个带标签的摘要指标 + Schema + 漂移
        self.summary_fields = self._metric(i18n.tr("字段数"), "0")
        self.summary_depth = self._metric(i18n.tr("层级"), "0")
        self.summary_arrays = self._metric(i18n.tr("数组"), "0")
        self.schema_view = CodeView(read_only=True, highlight=True, show_gutter=False)
        self.drift_view = QTextBrowser()
        self.drift_view.setReadOnly(True)
        self.drift_view.setObjectName("Bare")
        self.drift_view.setFont(mono(11.0))
        self.drift_view.setOpenExternalLinks(False)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(2, 2, 6, 2)
        ll.setSpacing(7)
        ll.addWidget(actions)
        ll.addWidget(Divider())
        summary = HBox((self.summary_fields, 1), (self.summary_depth, 1),
                       (self.summary_arrays, 1), spacing=10, margins=(2, 0, 2, 0))
        ll.addWidget(summary)
        ll.addWidget(Label("契约 Schema", 10.8, theme().text_dim,
                           weight=font(10.8).weight()))
        ll.addWidget(self.schema_view, 2)
        ll.addWidget(Label("字段漂移", 10.8, theme().text_dim,
                           weight=font(10.8).weight()))
        ll.addWidget(self.filter)
        ll.addWidget(self.drift_view, 1)

        # ---- 右栏：观测。指标改成紧凑行，不再用大卡片 1:1 平分
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 2, 2, 2)
        rl.setSpacing(7)
        self.kpi_status = self._metric(i18n.tr("状态"), "—", accent=True)
        self.kpi_duration = self._metric(i18n.tr("耗时"), "—")
        self.kpi_size = self._metric(i18n.tr("响应体"), "—")
        self.kpi_type = self._metric("Content-Type", "—")
        for m in (self.kpi_status, self.kpi_duration, self.kpi_size, self.kpi_type):
            rl.addWidget(m)
        rl.addWidget(Divider())
        rl.addWidget(Label("观测", 10.8, theme().text_dim,
                           weight=font(10.8).weight()))
        self.rows = {
            "dns": _TimingRow("DNS", False),
            "tcp": _TimingRow("TCP", False),
            "ssl": _TimingRow("TLS", False),
            "ttfb": _TimingRow("TTFB", True),
            "download": _TimingRow("Download", True),
        }
        for row in self.rows.values():
            rl.addWidget(row)
        rl.addStretch(1)
        self.obs_note = Label(
            "DNS / TCP / TLS 为估算值，仅 TTFB 与下载为真测。",
            10.0, theme().text_faint)
        self.obs_note.setWordWrap(True)
        rl.addWidget(self.obs_note)
        self.obs_detail = Label("", 10.0, theme().text_dim, mono_font=True)
        self.obs_detail.setWordWrap(True)
        rl.addWidget(self.obs_detail)

        self.split = _Splitter(Qt.Orientation.Horizontal)
        self.split.addWidget(left)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 1)
        self.split.setChildrenCollapsible(False)
        self.split.splitterMoved.connect(self._queue_split_save)
        self._split_timer = QTimer(self)
        self._split_timer.setSingleShot(True)
        self._split_timer.timeout.connect(self._persist_split)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(0)
        lay.addWidget(self.split, 1)

    @staticmethod
    def _metric(caption: str, value: str = "—", accent: bool = False) -> _Metric:
        return _Metric(caption, value, accent)

    def set_store(self, store) -> None:
        self.store = store
        QTimer.singleShot(0, self._restore_split)

    # -------------------------------------------------------- 分栏比例
    def _settings(self) -> Dict[str, Any]:
        data = getattr(self.store, "settings", None) if self.store else None
        return data if isinstance(data, dict) else {}

    def _restore_split(self) -> None:
        saved = self._settings().get("contract_split")
        self._restoring = True
        if isinstance(saved, list) and len(saved) == 2 \
                and all(isinstance(x, int) and x > 0 for x in saved):
            self.split.setSizes(saved)
        else:
            width = max(400, self.split.width())
            self.split.setSizes([width // 2, width // 2])
        self._restoring = False

    def _queue_split_save(self) -> None:
        if not self._restoring:
            self._split_timer.start(400)

    def _persist_split(self) -> None:
        if self.store is None:
            return
        self._settings()["contract_split"] = list(self.split.sizes())
        try:
            self.store.save()
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------- 数据入口
    def set_data(self, key: str, body: bytes, content_type: str,
                 timing: Optional[Dict[str, int]] = None,
                 meta: Optional[Dict[str, Any]] = None) -> None:
        self._key = key or ""
        self._body = body or b""
        self._content_type = content_type or ""
        self._timing = dict(timing or {})
        self._meta = dict(meta or {})
        saved = contract.get_contract(self.store, self._key)
        schema = saved.get("schema") if isinstance(saved, dict) else None
        if isinstance(schema, dict):
            self.schema_view.setPlainText(json.dumps(schema, ensure_ascii=False, indent=2))
            self._set_summary(schema)
        else:
            self.schema_view.setPlainText("")
            self._set_summary(None)
        self._check(silent=True)
        self._refresh_observability()

    def _set_summary(self, schema: Optional[Dict[str, Any]]) -> None:
        data = contract.summarize(schema) if schema else {"fields": 0, "depth": 0, "arrays": 0}
        self.summary_fields.set_value(str(data["fields"]))
        self.summary_depth.set_value(str(data["depth"]))
        self.summary_arrays.set_value(str(data["arrays"]))

    def _refresh_observability(self) -> None:
        t = theme()
        status = self._meta.get("status") or 0
        self.kpi_status.set_value(str(status) if status else "—")
        self.kpi_status.value.setStyleSheet(
            f"color: {S(t.success if 200 <= int(status or 0) < 400 else t.text)};")
        duration = int(self._meta.get("elapsed") or
                       (self._timing.get("ttfb", 0) + self._timing.get("download", 0)))
        self.kpi_duration.set_value(f"{duration} ms")
        size = int(self._meta.get("size") or len(self._body))
        self.kpi_size.set_value(self._human(size))
        ct = str(self._meta.get("content_type") or self._content_type or "—")
        self.kpi_type.set_value(ct.split(";")[0])

        dns = int(self._timing.get("dns") or 0)
        tcp = int(self._timing.get("tcp") or 0)
        ssl = int(self._timing.get("ssl") or 0)
        ttfb = int(self._timing.get("ttfb") or 0)
        download = int(self._timing.get("download") or 0)
        base = max(1, dns + tcp + ssl + ttfb + download)
        for key, value in (("dns", dns), ("tcp", tcp), ("ssl", ssl),
                           ("ttfb", ttfb), ("download", download)):
            self.rows[key].set_value(value)
            self.rows[key].bar.set_ratio(value / base)
        self.obs_note.setText(i18n.tr(
            "DNS / TCP / TLS 为估算值，仅 TTFB 与下载为真测。"))
        req_size = int(self._meta.get("request_size") or 0)
        req_head = int(self._meta.get("request_header_size") or 0)
        resp_head = int(self._meta.get("header_size") or 0)
        self.obs_detail.setText(i18n.trf(
            "请求头 {h} B · 请求体 {b} B · 响应头 {rh} B · 响应体 {rb} B",
            h=req_head, b=req_size, rh=resp_head, rb=size))

    @staticmethod
    def _human(n: int) -> str:
        value = float(max(0, n))
        for unit in ("B", "KB", "MB"):
            if value < 1024 or unit == "MB":
                return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{int(value)} B"

    # -------------------------------------------------------- 契约动作
    def _save(self) -> None:
        data, err = contract.parse_json(self._body, self._content_type)
        if err:
            self._set_result(err)
            return
        schema = contract.infer(data)
        contract.save_contract(self.store, self._key, schema, data)
        self.schema_view.setPlainText(json.dumps(schema, ensure_ascii=False, indent=2))
        self._set_summary(schema)
        self.status.setText(i18n.tr("契约已保存"))
        self._set_result(i18n.tr("已保存当前响应结构，之后的响应都会按它检查。"))

    def _check(self, silent: bool = False) -> None:
        saved = contract.get_contract(self.store, self._key)
        if not saved or not saved.get("schema"):
            if not silent:
                self.status.setText(i18n.tr("请先保存契约"))
            return
        data, err = contract.parse_json(self._body, self._content_type)
        if err:
            if not silent:
                self._set_result(i18n.trf("无法检查：{err}", err=err))
            return
        self._issues = contract.drift(saved["schema"], data)
        self._render_drift()
        if self._issues:
            self.status.setText(i18n.trf("发现 {n} 处字段漂移", n=len(self._issues)))
        else:
            self.status.setText(i18n.tr("契约一致"))

    def _render_drift(self) -> None:
        kind = self.filter.current()
        issues = self._issues
        if kind == "missing":
            issues = [x for x in issues if "字段消失" in x]
        elif kind == "new":
            issues = [x for x in issues if "新增字段" in x]
        elif kind == "type":
            issues = [x for x in issues if "类型由" in x]
        t = theme()
        if not issues:
            color = S(t.success)
            text = i18n.tr("✓ 字段与契约完全一致")
            self.drift_view.setHtml(
                f'<div style="color:{color};font-size:11px;padding:5px 2px">{html.escape(text)}</div>')
            return
        rows = []
        for item in issues:
            if "字段消失" in item:
                color = S(t.danger)
            elif "新增字段" in item:
                color = S(t.info)
            else:
                color = S(t.warning)
            rows.append(
                f'<div style="color:{color};font-size:10.8px;padding:2px 0">'
                f'✕ {html.escape(item)}</div>')
        self.drift_view.setHtml("".join(rows))

    def _clear(self) -> None:
        contract.remove_contract(self.store, self._key)
        self.schema_view.setPlainText("")
        self._set_summary(None)
        self.status.setText(i18n.tr("契约已删除"))
        self._issues = []
        self._render_drift()

    def _copy_schema(self) -> None:
        QGuiApplication.clipboard().setText(self.schema_view.toPlainText())
        self.status.setText(i18n.tr("契约 Schema 已复制"))

    def _set_result(self, text: str) -> None:
        self.drift_view.setPlainText(text)

    def refresh_theme(self) -> None:
        self._refresh_observability()
        self._render_drift()
