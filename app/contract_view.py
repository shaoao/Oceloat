"""契约页：为当前响应生成 / 比对 JSON Schema，并展示可测的真实耗时。

纯 UI，数据来自 app.contract；不联网、不额外占内存，切走即释放文本。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from . import contract, i18n
from .code_editor import CodeView
from .theme import font, mono, theme
from .widgets import Button, Divider, HBox, Label


class ContractView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = None
        self._key = ""
        self._body = b""
        self._content_type = ""
        self._timing: Dict[str, int] = {}

        self.status = Label("", 11.2, theme().text_faint, mono_font=True)
        self.status.setWordWrap(True)
        self.save_btn = Button("保存为契约", "plus", kind="subtle", height=24,
                               padding=8, font_size=11.5,
                               tooltip="把当前响应结构保存为该接口的基准契约")
        self.check_btn = Button("检查漂移", "refresh", kind="ghost", height=24,
                                padding=8, font_size=11.5,
                                tooltip="用已保存的契约比对当前响应字段")
        self.clear_btn = Button("删除契约", "trash", kind="ghost", height=24,
                                padding=8, font_size=11.5)
        self.save_btn.clicked.connect(self._save)
        self.check_btn.clicked.connect(self._check)
        self.clear_btn.clicked.connect(self._clear)

        self.schema_view = CodeView(read_only=True, highlight=True, show_gutter=False)
        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setObjectName("Bare")
        self.result_view.setFont(mono(11.3))
        self.result_view.setMaximumHeight(110)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        lay.addWidget(HBox(self.status, 1, self.save_btn, self.check_btn,
                           self.clear_btn, spacing=6))
        lay.addWidget(Divider())
        lay.addWidget(Label("契约 Schema", 11.3, theme().text_dim,
                            weight=font(11.3).weight()))
        lay.addWidget(self.schema_view, 1)
        lay.addWidget(Label("观测", 11.3, theme().text_dim))
        lay.addWidget(self.result_view)

    def set_store(self, store) -> None:
        self.store = store

    def set_data(self, key: str, body: bytes, content_type: str,
                 timing: Optional[Dict[str, int]] = None) -> None:
        self._key = key or ""
        self._body = body or b""
        self._content_type = content_type or ""
        self._timing = dict(timing or {})
        saved = contract.get_contract(self.store, self._key)
        if saved and isinstance(saved.get("schema"), dict):
            self.schema_view.setPlainText(json.dumps(
                saved["schema"], ensure_ascii=False, indent=2))
            self.status.setText(i18n.tr("已有契约 · 可检查当前响应是否漂移"))
        else:
            self.schema_view.setPlainText("")
            self.status.setText(i18n.tr("尚无契约 · 保存当前响应后即可持续守护字段"))
        self._refresh_timing()

    def _refresh_timing(self) -> None:
        measured = self._timing.get("ttfb") or 0
        download = self._timing.get("download") or 0
        total = measured + download
        lines = [
            i18n.tr("TTFB（实测）：{n} ms", n=measured),
            i18n.tr("下载（实测）：{n} ms", n=download),
            i18n.tr("合计：{n} ms", n=total),
        ]
        if self._timing.get("dns") or self._timing.get("tcp") or self._timing.get("ssl"):
            lines.append(i18n.tr("DNS / TCP / TLS 为估算值，仅 TTFB 与下载为真测。"))
        self.result_view.setPlainText("\n".join(lines))

    def _set_result(self, text: str) -> None:
        self.result_view.setPlainText(text)

    def _save(self) -> None:
        data, err = contract.parse_json(self._body, self._content_type)
        if err:
            self._set_result(i18n.trf("无法保存：{err}", err=err))
            return
        schema = contract.infer(data)
        contract.save_contract(self.store, self._key, schema, data)
        self.schema_view.setPlainText(json.dumps(schema, ensure_ascii=False, indent=2))
        self.status.setText(i18n.tr("契约已保存"))
        self._set_result(i18n.tr("已保存当前响应结构，之后的响应都会按它检查。"))

    def _check(self) -> None:
        saved = contract.get_contract(self.store, self._key)
        if not saved or not saved.get("schema"):
            self.status.setText(i18n.tr("请先保存契约"))
            return
        data, err = contract.parse_json(self._body, self._content_type)
        if err:
            self._set_result(i18n.trf("无法检查：{err}", err=err))
            return
        issues = contract.drift(saved["schema"], data)
        if issues:
            self.status.setText(i18n.trf("发现 {n} 处字段漂移", n=len(issues)))
            self._set_result("\n".join("✕ " + x for x in issues))
        else:
            self.status.setText(i18n.tr("契约一致"))
            self._set_result(i18n.tr("✓ 字段与契约完全一致"))

    def _clear(self) -> None:
        contract.remove_contract(self.store, self._key)
        self.schema_view.setPlainText("")
        self.status.setText(i18n.tr("契约已删除"))
        self._set_result("")

    def refresh_theme(self) -> None:
        self._refresh_timing()
