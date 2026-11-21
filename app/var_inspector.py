"""变量侦探：一个变量在哪定义、被谁覆盖、谁在引用，全部列清楚。

只读分析，不改数据；复用 Store.env_vars / global_vars / walk / env_refs，
不引入额外依赖。界面是卡片 + 详情左右分栏，避免旧表格的红框与大块空白。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QFileDialog, QLineEdit, QSplitter, QVBoxLayout, QWidget

from . import i18n
from .dialogs import GlassDialog
from .share import is_secret_key
from .theme import font, theme
from .widgets import (
    Button, Card, Divider, EmptyState, HBox, Label, Pill, SegmentedTabs,
    SmoothScrollArea, Switch,
)

_NAME = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_BUILTINS = ("timestamp", "uuid", "randomInt", "date", "time")


def collect(store) -> List[Dict[str, Any]]:
    """汇总所有变量：全局 / 当前环境 / 运行时 / 内置动态 / 引用。"""
    env = store.env_vars() if store else {}
    rows: Dict[str, Dict[str, Any]] = {}

    def row(name: str) -> Dict[str, Any]:
        return rows.setdefault(name, {
            "name": name, "sources": [], "refs": [], "ref_ids": [],
        })

    for item in (store.global_vars() if store else []) or []:
        if isinstance(item, dict) and item.get("key"):
            row(str(item["key"]))["sources"].append(
                {"label": i18n.tr("全局"), "value": str(item.get("value") or ""),
                 "scope": "global"})

    env_obj = store.active_environment() if store else None
    if isinstance(env_obj, dict):
        title = str(env_obj.get("name") or i18n.tr("环境"))
        for item in env_obj.get("vars") or []:
            if isinstance(item, dict) and item.get("key"):
                row(str(item["key"]))["sources"].append(
                    {"label": title, "value": str(item.get("value") or ""),
                     "scope": "env"})

    for name, value in (env or {}).items():
        r = row(str(name))
        if not r["sources"]:
            r["sources"].append({"label": i18n.tr("运行时"),
                                 "value": str(value), "scope": "runtime"})
    for name in _BUILTINS:
        row("$" + name)["sources"].append({
            "label": i18n.tr("内置动态"), "value": i18n.tr("每次发送时现算"),
            "scope": "builtin"})

    for node in (store.walk() if store else []) or []:
        if not isinstance(node, dict) or node.get("type") != "request":
            continue
        names = store.env_refs(node) if hasattr(store, "env_refs") else []
        title = str(node.get("name") or node.get("url") or i18n.tr("请求"))
        for name in names or []:
            r = row(str(name))
            r["refs"].append(title)
            r["ref_ids"].append(str(node.get("id") or ""))

    defined = set(env.keys()) | set(_BUILTINS)
    for name, r in rows.items():
        scopes = {s.get("scope") for s in r["sources"]}
        r["scopes"] = sorted(x for x in scopes if x)
        r["missing"] = not r["sources"] and bool(r["refs"]) and name not in defined
        r["unused"] = not r["refs"]
        r["conflict"] = len(scopes) > 1
        r["secret"] = is_secret_key(name)
        r["primary"] = _primary_scope(r)
    return [rows[k] for k in sorted(rows, key=lambda s: str(s).lower())]


def _primary_scope(row: Dict[str, Any]) -> str:
    for scope in ("env", "global", "runtime", "builtin"):
        if scope in row.get("scopes", []):
            return scope
    return "missing" if row.get("missing") else "unused"


class _VarCard(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, row: Dict[str, Any], value: str, parent=None):
        super().__init__(parent)
        self.name = str(row["name"])
        self.card = Card(radius=9)
        lay = HBox(spacing=8)
        lay.setContentsMargins(11, 8, 11, 8)
        # 小圆点统一走主题色：不同来源只改透明度，不用红黄蓝绿杂色
        dot_color = {"env": theme().accent, "global": theme().text,
                     "runtime": theme().accent, "builtin": theme().text_dim}.get(
                         row.get("primary"), theme().accent)
        self.dot = Pill("", color=dot_color, dot=True, height=18)
        self.name_label = Label(self.name, 12.2, theme().text,
                                weight=font(12.2).weight(), mono_font=True)
        self.value_label = Label(value or "—", 10.8, theme().text_faint, mono_font=True)
        self.value_label.setMaximumWidth(240)
        self.badges = HBox(spacing=4)
        lay.layout().addWidget(self.dot)
        lay.layout().addWidget(self.name_label, 1)
        lay.layout().addWidget(self.value_label)
        lay.layout().addWidget(self.badges)
        self.card.setLayout(QVBoxLayout())
        self.card.layout().addWidget(lay)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)
        self.set_selected(False)
        self._apply_badges(row)

    def _apply_badges(self, row: Dict[str, Any]) -> None:
        # 纯黑主题：徽标靠白灰明暗层次，只有「未定义」这种真问题才用危险色
        if row.get("missing"):
            self.badges.layout().addWidget(
                Pill(i18n.tr("未定义"), color="danger", height=17))
        if row.get("conflict"):
            self.badges.layout().addWidget(
                Pill(i18n.tr("冲突"), color=theme().text, height=17))
        if row.get("unused"):
            self.badges.layout().addWidget(
                Pill(i18n.tr("未引用"), color="text_faint", height=17))
        if row.get("secret"):
            self.badges.layout().addWidget(
                Pill(i18n.tr("敏感"), color=theme().text_dim, height=17))

    def set_selected(self, selected: bool) -> None:
        t = theme()
        self.card._fill = t.accent_soft if selected else t.card
        self.card._border = selected
        self.name_label.setStyleSheet(
            f"color: {t.accent};" if selected else "")
        self.card.update()

    def mousePressEvent(self, e) -> None:
        self.clicked.emit(self.name)
        super().mousePressEvent(e)


class VarInspectorDialog(GlassDialog):
    """非模态侦探窗：一边看变量，一边还能在主界面操作。"""

    MODELESS = True
    FILTERS = [
        ("all", "全部"), ("global", "全局"), ("env", "环境"),
        ("runtime", "运行时"), ("builtin", "内置"),
        ("unused", "未引用"), ("missing", "未定义"),
    ]

    def __init__(self, store, parent=None):
        super().__init__(parent, 940, 640, i18n.tr("变量侦探"))
        self.store = store
        self._rows = collect(store)
        self._selected = ""
        self._show_secrets = False
        t = theme()

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 12, 18, 16)
        lay.setSpacing(9)

        self.kpis = HBox(spacing=6)
        self.kpi_total = self._kpi("0", i18n.tr("变量总数"))
        self.kpi_env = self._kpi("0", i18n.tr("环境"))
        self.kpi_refs = self._kpi("0", i18n.tr("引用"))
        self.kpi_problem = self._kpi("0", i18n.tr("待处理"))
        for widget in (self.kpi_total, self.kpi_env, self.kpi_refs, self.kpi_problem):
            self.kpis.layout().addWidget(widget, 1)
        lay.addWidget(self.kpis)

        self.search = QLineEdit()
        self.search.setObjectName("Field")
        self.search.setFixedHeight(30)
        self.search.setFont(font(11.8))
        i18n.placeholder(self.search, i18n.tr("搜索变量名 / 来源 / 引用它的请求"))
        self.search.textChanged.connect(self._rebuild)

        self.filters = SegmentedTabs(self.FILTERS, style="pill", height=26,
                                     font_size=10.8, pad_h=9)
        self.filters.set_current("all", emit=False)
        self.filters.changed.connect(lambda _k: self._rebuild())
        self.mask_switch = Switch(False)
        self.mask_switch.toggled.connect(self._on_mask)
        self.refresh_btn = Button("刷新", "refresh", kind="ghost", height=28,
                                  padding=10, font_size=11.5)
        self.export_btn = Button("导出 JSON", "download", kind="subtle", height=28,
                                 padding=10, font_size=11.5)
        self.refresh_btn.clicked.connect(self._refresh)
        self.export_btn.clicked.connect(self._export)
        lay.addWidget(HBox(
            (self.search, 1), self.filters,
            Label(i18n.tr("显示密钥"), 10.6, t.text_faint), self.mask_switch,
            self.refresh_btn, self.export_btn, spacing=8))

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 1)

        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 6, 0)
        self.list_lay.setSpacing(6)
        self.list_scroll = SmoothScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_panel = QWidget()
        self.list_panel_lay = QVBoxLayout(self.list_panel)
        self.list_panel_lay.setContentsMargins(0, 0, 0, 0)
        self.list_panel_lay.setSpacing(6)
        self.list_scroll.setWidget(self.list_panel)
        self.list_lay.addWidget(self.list_scroll, 1)

        self.detail = QWidget()
        self.detail_lay = QVBoxLayout(self.detail)
        self.detail_lay.setContentsMargins(10, 2, 0, 0)
        self.detail_lay.setSpacing(9)
        self.split.addWidget(self.list_host)
        self.split.addWidget(self.detail)
        lay.addWidget(self.split, 1)

        close = Button("关闭", None, kind="ghost", height=28, padding=12, font_size=12)
        close.clicked.connect(self.accept)
        lay.addWidget(HBox(1, close, spacing=6))

        self._render_kpis()
        self._rebuild()
        width = max(400, self.split.width())
        self.split.setSizes([int(width * 0.58), int(width * 0.42)])

    @staticmethod
    def _kpi(value: str, caption: str) -> QWidget:
        card = Card(radius=8)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(2)
        v = Label(value, 13.5, theme().text, weight=font(13.5).weight(), mono_font=True)
        v.setObjectName("var_kpi_value")
        lay.addWidget(v)
        lay.addWidget(Label(caption, 10.2, theme().text_faint))
        return card

    def _set_kpi(self, widget: QWidget, value: str) -> None:
        widget.findChild(Label, "var_kpi_value").setText(value)

    def _render_kpis(self) -> None:
        refs = sum(len(r["refs"]) for r in self._rows)
        problems = sum(1 for r in self._rows if r.get("missing") or r.get("conflict"))
        self._set_kpi(self.kpi_total, str(len(self._rows)))
        self._set_kpi(self.kpi_env, str(len(
            {s["label"] for r in self._rows for s in r["sources"]
             if s.get("scope") == "env"})))
        self._set_kpi(self.kpi_refs, str(refs))
        self._set_kpi(self.kpi_problem, str(problems))
        self.kpi_problem.findChild(Label, "var_kpi_value").setStyleSheet(
            f"color: {theme().danger};" if problems else "")

    def _visible_rows(self) -> List[Dict[str, Any]]:
        needle = (self.search.text() or "").strip().lower()
        kind = self.filters.current()
        out = []
        for r in self._rows:
            if kind == "unused" and not r.get("unused"):
                continue
            if kind == "missing" and not r.get("missing"):
                continue
            if kind in ("global", "env", "runtime", "builtin") \
                    and kind not in r.get("scopes", []):
                continue
            blob = " ".join([r["name"]] +
                            [str(s.get("label")) + str(s.get("value"))
                             for s in r["sources"]] + list(r["refs"])).lower()
            if needle and needle not in blob:
                continue
            out.append(r)
        return out

    def _display_value(self, row: Dict[str, Any]) -> str:
        env = self.store.env_vars() if self.store else {}
        value = str(env.get(row["name"], "") or "")
        if not value and row["sources"]:
            value = str(row["sources"][0].get("value") or "")
        if row.get("secret") and not self._show_secrets and value:
            return "••••••" + value[-3:]
        return value or "—"

    def _rebuild(self) -> None:
        while self.list_panel_lay.count():
            item = self.list_panel_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = self._visible_rows()
        if not rows:
            self.list_panel_lay.addWidget(EmptyState(
                "search", i18n.tr("没有匹配的变量"),
                i18n.tr("换个关键词或筛选条件试试"), parent=self.list_panel), 1)
        for row in rows:
            card = _VarCard(row, self._display_value(row))
            card.clicked.connect(self._select)
            card.setProperty("var_name", row["name"])
            self.list_panel_lay.addWidget(card)
        self.list_panel_lay.addStretch(1)
        names = {r["name"] for r in rows}
        if self._selected not in names:
            self._selected = rows[0]["name"] if rows else ""
        self._render_detail()

    def _select(self, name: str) -> None:
        self._selected = name
        for i in range(self.list_panel_lay.count()):
            widget = self.list_panel_lay.itemAt(i).widget()
            if isinstance(widget, _VarCard):
                widget.set_selected(widget.name == name)
        self._render_detail()

    def _row(self) -> Optional[Dict[str, Any]]:
        return next((r for r in self._rows if r["name"] == self._selected), None)

    def _render_detail(self) -> None:
        while self.detail_lay.count():
            item = self.detail_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        row = self._row()
        if not row:
            self.detail_lay.addWidget(EmptyState(
                "search", i18n.tr("选择一个变量"),
                i18n.tr("左侧卡片里点一个变量，这里会显示它的来源与引用"),
                parent=self.detail), 1)
            return
        t = theme()
        kind = row["primary"]
        kind_labels = {"global": "全局", "env": "环境", "runtime": "运行时",
                       "builtin": "内置动态", "missing": "未定义",
                       "unused": "未引用"}
        color = {"global": t.text_dim, "env": t.accent, "runtime": t.text,
                 "builtin": t.text_faint, "missing": t.danger,
                 "unused": t.text_faint}.get(kind, t.accent)
        self.detail_lay.addWidget(HBox(
            Pill(i18n.tr(kind_labels.get(kind, "全局")), color=color, height=20),
            (Label(row["name"], 16, t.text, weight=font(16).weight(),
                   mono_font=True), 1), spacing=8))
        self.detail_lay.addWidget(Divider())

        value = self._display_value(row)
        self.detail_lay.addWidget(Label(i18n.tr("当前值"), 10.8, t.text_faint))
        value_card = Card(radius=8)
        vl = QVBoxLayout(value_card)
        vl.setContentsMargins(10, 9, 10, 9)
        vl.addWidget(Label(value, 12.4, t.text, mono_font=True))
        copy_value = Button(i18n.tr("复制值"), "copy", kind="ghost", height=24,
                            padding=8, font_size=10.8)
        copy_name = Button(i18n.tr("复制变量名"), "copy", kind="ghost", height=24,
                           padding=8, font_size=10.8)
        copy_value.clicked.connect(lambda: QGuiApplication.clipboard().setText(value))
        copy_name.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(row["name"]))
        vl.addWidget(HBox(copy_value, copy_name, spacing=6))
        self.detail_lay.addWidget(value_card)

        self.detail_lay.addWidget(Label(i18n.tr("来源"), 10.8, t.text_faint))
        if not row["sources"]:
            self.detail_lay.addWidget(Label(
                i18n.tr("未定义：只在请求里被引用"), 11.2, t.danger))
        source_colors = {"global": t.text_dim, "env": t.accent, "runtime": t.text,
                         "builtin": t.text_faint}
        for src in row["sources"]:
            self.detail_lay.addWidget(HBox(
                Pill(src["label"], color=source_colors.get(
                    src.get("scope"), "text_faint"), height=18),
                (Label(str(src["value"]), 11.2, t.text_dim, mono_font=True), 1),
                spacing=7))
        self.detail_lay.addWidget(Label(i18n.tr("引用它的请求"), 10.8, t.text_faint))
        if not row["refs"]:
            self.detail_lay.addWidget(Label(i18n.tr("暂时没有请求引用"), 11.2, t.text_faint))
        else:
            for name in row["refs"][:12]:
                self.detail_lay.addWidget(Label("•  " + name, 11.2, t.text_dim))
            if len(row["refs"]) > 12:
                self.detail_lay.addWidget(Label(
                    i18n.trf("还有 {n} 个…", n=len(row["refs"]) - 12),
                    10.6, t.text_faint))
        chain = self._resolve_chain(row["name"])
        if len(chain) > 1:
            self.detail_lay.addWidget(Label(i18n.tr("解析链"), 10.8, t.text_faint))
            self.detail_lay.addWidget(Label(" → ".join(chain), 11.2, t.accent,
                                            mono_font=True))
        self.detail_lay.addStretch(1)

    def _resolve_chain(self, name: str) -> List[str]:
        env = self.store.env_vars() if self.store else {}
        chain: List[str] = [name]
        seen = {name}
        current = str(env.get(name) or "")
        for _ in range(6):
            names = [m.group(1) for m in _NAME.finditer(current) if m.group(1) not in seen]
            if not names:
                break
            nxt = names[0]
            chain.append(nxt)
            seen.add(nxt)
            current = str(env.get(nxt) or "")
        if current and not _NAME.search(current):
            chain.append(current[:40] + ("…" if len(current) > 40 else ""))
        return chain

    # ------------------------------------------------------------ 动作
    def _on_mask(self, _checked: bool) -> None:
        self._show_secrets = not self._show_secrets
        self._rebuild()

    def _refresh(self) -> None:
        self._rows = collect(self.store)
        self._render_kpis()
        self._rebuild()
        self.refresh_btn.spin_once()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("导出变量快照"), "ocelot-variables.json", "JSON (*.json)")
        if not path:
            return
        payload = [{
            "name": r["name"],
            "sources": r["sources"],
            "references": r["refs"],
            "missing": bool(r.get("missing")),
            "unused": bool(r.get("unused")),
        } for r in self._rows]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def refresh_theme(self) -> None:
        self._rebuild()
