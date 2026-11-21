"""变量侦探：一个变量在哪定义、被谁覆盖、谁在引用，全部列清楚。

只读分析，不改数据；复用 Store.env_refs / env_vars / walk，不引入额外依赖。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from . import i18n
from .dialogs import GlassDialog
from .theme import mono, theme
from .widgets import Button, Divider, HBox, Label

_NAME = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def collect(store) -> List[Dict[str, Any]]:
    """汇总所有变量：全局 / 当前环境 / 动态内置 / 请求引用。"""
    env = store.env_vars() if store else {}
    rows: Dict[str, Dict[str, Any]] = {}

    def row(name: str) -> Dict[str, Any]:
        return rows.setdefault(name, {"name": name, "sources": [], "refs": []})

    global_vars = store.global_vars() if store else []
    for item in global_vars or []:
        if isinstance(item, dict) and item.get("key"):
            row(str(item["key"]))["sources"].append(
                (i18n.tr("全局"), str(item.get("value") or "")))
    env_obj = store.active_environment() if store else None
    if isinstance(env_obj, dict):
        title = str(env_obj.get("name") or i18n.tr("环境"))
        for item in env_obj.get("vars") or []:
            if isinstance(item, dict) and item.get("key"):
                row(str(item["key"]))["sources"].append((title, str(item.get("value") or "")))
    for name, value in (env or {}).items():
        r = row(str(name))
        if not r["sources"]:
            r["sources"].append((i18n.tr("运行时"), str(value)))
    for name in ("timestamp", "uuid", "randomInt", "date", "time"):
        row("$" + name)["sources"].append((i18n.tr("内置动态"), i18n.tr("每次发送时现算")))

    for node in store.walk() if store else []:
        if not isinstance(node, dict) or node.get("type") != "request":
            continue
        names = store.env_refs(node) if hasattr(store, "env_refs") else []
        title = str(node.get("name") or node.get("url") or i18n.tr("请求"))
        for name in names or []:
            row(str(name))["refs"].append(title)
    return [rows[k] for k in sorted(rows, key=lambda s: str(s).lower())]


class VarInspectorDialog(GlassDialog):
    """非模态侦探窗：一边看变量，一边还能在主界面操作。"""

    MODELESS = True

    def __init__(self, store, parent=None):
        super().__init__(parent, 720, 520, i18n.tr("变量侦探"))
        self.store = store
        self._rows = collect(store)
        t = theme()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 12, 18, 16)
        lay.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("Field")
        self.search.setFixedHeight(30)
        self.search.setFont(mono(11.8))
        i18n.placeholder(self.search, i18n.tr("搜索变量名 / 来源 / 引用它的请求"))
        self.search.textChanged.connect(self._rebuild)
        lay.addWidget(self.search)
        self.summary = Label("", 10.6, t.text_faint)
        lay.addWidget(self.summary)
        lay.addWidget(Divider())
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([i18n.tr("变量"), i18n.tr("当前值"), i18n.tr("来源 / 引用")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setFont(mono(11.2))
        lay.addWidget(self.tree, 1)
        close = Button("关闭", None, kind="ghost", height=28, padding=12, font_size=12)
        close.clicked.connect(self.accept)
        lay.addWidget(HBox(1, close, spacing=6))
        self._rebuild()

    def _rebuild(self, _text: str = "") -> None:
        needle = (self.search.text() or "").strip().lower()
        self.tree.clear()
        shown = 0
        env = self.store.env_vars() if self.store else {}
        for row in self._rows:
            name = str(row["name"])
            sources = " · ".join(f"{s}: {v}" for s, v in row["sources"])
            refs = ", ".join(row["refs"][:4])
            extra = (i18n.trf("  [{n} 处引用]", n=len(row["refs"]))
                     if len(row["refs"]) > 4 else "")
            blob = f"{name} {sources} {refs}".lower()
            if needle and needle not in blob:
                continue
            quoted = i18n.tr("\n引用：")
            item = QTreeWidgetItem([name, str(env.get(name, "") or "—"),
                                    sources + (quoted + refs + extra if refs else "")])
            item.setToolTip(2, sources + (quoted + ", ".join(row["refs"]) if refs else ""))
            self.tree.addTopLevelItem(item)
            shown += 1
        self.summary.setText(i18n.trf("共 {n} 个变量 · 显示 {m} 个",
                                      n=len(self._rows), m=shown))
        for i, width in enumerate((180, 220, 280)):
            self.tree.setColumnWidth(i, width)
