"""GraphQL 请求体页：查询编辑（Schema 补全）+ 变量 + 操作选择 + 生成 / AI 写查询。

界面只占请求体里的一页，和 JSON / XML 平级；不开新窗口、不加常驻线程。
Schema 走一次内省查询拉取，复用 ApiClient（认证 / 代理 / 证书设置全都生效），
结果按地址缓存在进程内，切标签不用重拉。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QTextCursor
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from . import graphql as gql
from . import i18n, icons
from .code_editor import CodeView
from .store import resolve_vars
from .theme import theme
from .widgets import Button, Card, HBox, Label, Menu, SuggestPopup

_SCHEMAS: Dict[str, gql.Schema] = {}        # 地址 → Schema，进程内缓存


def _key(url: str) -> str:
    return (url or "").split("?")[0].split("#")[0].rstrip("/")


class _FieldPopup(SuggestPopup):
    """补全浮层：复用地址栏候选的绘制，只改成贴着光标弹。"""

    MAX_ROWS = 9

    def popup_at(self, editor: CodeView) -> None:
        win = editor.window()
        if win is None:
            return
        self.setParent(win)
        self._width = 340
        self.setFixedWidth(self._width)
        rect = editor.cursorRect()
        pos = editor.viewport().mapTo(win, QPoint(rect.left() - 8, rect.bottom() + 6))
        if pos.y() + self.height() > win.height() - 8:
            pos = editor.viewport().mapTo(win, QPoint(rect.left() - 8, rect.top() - self.height() - 6))
        pos.setX(max(8, min(pos.x(), win.width() - self._width - 8)))
        self.move(pos)
        self.show()
        self.raise_()


class _CardCode(CodeView):
    TRANSPARENT = True


class GqlEditor(_CardCode):
    """查询编辑器：输入字母自动补全当前选择集的字段，⌃Space 强制弹出。"""

    needSchema = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(read_only=False, highlight=True, show_gutter=True, wrap=False,
                         parent=parent)
        self.set_language("graphql")
        self.schema_fn: Callable[[], Optional[gql.Schema]] = lambda: None
        self._pop: Optional[_FieldPopup] = None
        self._rows: list = []
        self._prefix = ""

    def _popup(self) -> _FieldPopup:
        if self._pop is None:
            self._pop = _FieldPopup(self, "code")
            self._pop.picked.connect(self._accept)
        return self._pop

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        pop = self._pop
        key = e.key()
        if pop is not None and pop.isVisible():
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                pop.step(-1 if key == Qt.Key.Key_Up else 1)
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self._accept(pop.current() or "")
                return
            if key == Qt.Key.Key_Escape:
                pop.hide()
                return
        mods = e.modifiers()
        if key == Qt.Key.Key_Space and mods & (Qt.KeyboardModifier.MetaModifier
                                                | Qt.KeyboardModifier.ControlModifier):
            self.complete(force=True)
            return
        super().keyPressEvent(e)
        ch = e.text()
        if ch and (ch.isalnum() or ch == "_"):
            self.complete()
        elif key == Qt.Key.Key_Backspace and pop is not None and pop.isVisible():
            self.complete()
        elif pop is not None:
            pop.hide()

    def focusOutEvent(self, e):  # noqa: N802
        if self._pop is not None:
            QTimer.singleShot(120, self._pop.hide)   # 先让鼠标点选生效
        super().focusOutEvent(e)

    def complete(self, force: bool = False) -> None:
        schema = self.schema_fn()
        if schema is None:
            if force:
                self.needSchema.emit()
            return
        text = self.toPlainText()
        pos = self.textCursor().position()
        self._prefix, self._rows = gql.suggest(schema, text, pos)
        pop = self._popup()
        if not self._rows or (not force and not self._prefix):
            pop.hide()
            return
        pop.set_items([f"{r['name']}  ·  {r['sig']}" + ("  · " + i18n.tr("弃用") if r["deprecated"] else "")
                       for r in self._rows])
        pop.popup_at(self)

    def _accept(self, label: str) -> None:
        if self._pop is not None:
            self._pop.hide()
        name = label.split("  ")[0].strip()
        row = next((r for r in self._rows if r["name"] == name), None)
        if row is None:
            return
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor,
                         len(self._prefix))
        indent = cur.block().text()[:len(cur.block().text()) - len(cur.block().text().lstrip())]
        required = [a for a, t in row["args"] if t.endswith("!")]
        text = name + (f"({', '.join(a + ': ' for a in required)})" if required else "")
        if row["leaf"]:
            cur.insertText(text)
        else:
            cur.insertText(f"{text} {{\n{indent}  \n{indent}}}")
            cur.movePosition(QTextCursor.MoveOperation.Up)
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.setTextCursor(cur)


class GqlPage(QWidget):
    changed = pyqtSignal()
    notify = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 由 RequestEditor 注入：() -> (当前请求副本, 设置, 环境变量)
        self.ctx: Optional[Callable[[], tuple]] = None
        self._loading = False
        self._op = ""
        self._client = None
        self._chat = None
        self._ai_buf = ""

        self.query = GqlEditor()
        self.query.schema_fn = self.schema
        self.query.needSchema.connect(lambda: self.notify.emit(i18n.tr("先点「Schema」拉取结构，才能补全字段")))
        i18n.placeholder(self.query, "query { … }    先点 Schema，输入字段名即可补全 · ⌃Space 强制")
        self.query.textChanged.connect(self._edited)

        self.vars = _CardCode(read_only=False, highlight=True, show_gutter=True, wrap=False)
        i18n.placeholder(self.vars, '{ "id": 1 }    写了 $变量 后点「同步变量」自动补齐')
        self.vars.textChanged.connect(self._edited)

        def btn(text, icon, tip, cb, **kw):
            b = Button(text, icon, kind=kw.get("kind", "ghost"), height=24, padding=8,
                       font_size=11.5, icon_size=12, tooltip=tip,
                       mono_font=kw.get("mono", False))
            b.clicked.connect(cb)
            return b

        self.schema_btn = btn("Schema", "refresh", "发送内省查询，拉取字段用于补全与生成",
                              self.fetch_schema)
        self.schema_info = Label("", 10.5, theme().text_faint, mono_font=True)
        self.op_btn = btn("", None, "文档里有多个操作：选这次要执行的", self._pick_op, mono=True)
        self.gen_btn = btn("生成", "layers", "从 Schema 里选一个字段，生成可直接发送的查询",
                           self._gen_menu)
        self.ai_btn = btn("AI 写查询", "spark", "用一句话描述要查什么，按 Schema 写出查询",
                          self._ai_write)
        self.fmt_btn = btn("Format", None, "按层级整理缩进", self._format)
        tools = HBox(self.schema_btn, self.schema_info, 1, self.op_btn, self.gen_btn,
                     self.ai_btn, self.fmt_btn, spacing=4)

        self.sync_btn = btn("同步变量", None, "按查询里声明的 $变量 补齐变量 JSON", self._sync_vars)
        self.status = Label("", 10.5, theme().text_faint, mono_font=True)
        vhead = HBox(Label("变量", 10.5, theme().text_faint), 1, self.status, self.sync_btn,
                     spacing=6)

        qcard, vcard = Card(radius=9), Card(radius=9)
        for card, view in ((qcard, self.query), (vcard, self.vars)):
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 6, 0, 6)
            cl.addWidget(view, 1)
        vcard.setMinimumHeight(74)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(tools)
        lay.addWidget(qcard, 3)
        lay.addWidget(vhead)
        lay.addWidget(vcard, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._validate)
        self.op_btn.hide()

    # -------------------------------------------------- 数据
    def load(self, query: str, variables: str, op: str) -> None:
        self._loading = True
        self.query.setPlainText(query or "")
        self.vars.setPlainText(variables or "")
        self._op = op or ""
        self._loading = False
        self._validate()

    def dump(self) -> Dict[str, Any]:
        return {"raw": self.query.toPlainText(), "gql_vars": self.vars.toPlainText(),
                "gql_op": self._op}

    def has_content(self) -> bool:
        return self.query.document().characterCount() > 1

    def _edited(self) -> None:
        if self._loading:
            return
        self._timer.start()
        self.changed.emit()

    def _validate(self) -> None:
        q, v = self.query.toPlainText(), self.vars.toPlainText()
        err = gql.check(q, v)
        t = theme()
        if err:
            self.status.setText("✕ " + err)
            color = t.danger
        elif q.strip():
            n = len(gql._VAR_RE.findall(gql._strip(q)))
            self.status.setText("✓ GraphQL" + (i18n.trf(" · {n} 个变量", n=n) if n else ""))
            color = t.success
        else:
            self.status.setText("")
            color = t.text_faint
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        ops = gql.operations(q)
        if self._op not in ops:
            self._op = ops[0] if ops else ""
        self.op_btn.setVisible(len(ops) > 1)
        self.op_btn.setText("▸ " + self._op)

    def _pick_op(self) -> None:
        menu = Menu(self)
        acts = {menu.addAction(name): name for name in gql.operations(self.query.toPlainText())}
        chosen = menu.exec(self.op_btn.mapToGlobal(self.op_btn.rect().bottomLeft()))
        if chosen in acts:
            self._op = acts[chosen]
            self._validate()
            self.changed.emit()

    # -------------------------------------------------- Schema
    def _url(self) -> str:
        if not self.ctx:
            return ""
        req, _settings, env = self.ctx()
        return _key(resolve_vars(str(req.get("url") or ""), env))

    def schema(self) -> Optional[gql.Schema]:
        return _SCHEMAS.get(self._url())

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._show_schema_info()

    def _show_schema_info(self) -> None:
        s = self.schema()
        if s is None:
            self.schema_info.setText("")
            return
        q, m = s.counts()
        self.schema_info.setText(f"Q {q} · M {m}")

    def fetch_schema(self) -> None:
        if not self.ctx:
            return
        req, settings, env = self.ctx()
        if not str(req.get("url") or "").strip():
            self.notify.emit(i18n.tr("先填 GraphQL 地址"))
            return
        req = dict(req, method="POST", scripts={},
                   body={"mode": "graphql", "raw": gql.INTROSPECTION})
        if self._client is None:
            from .http_client import ApiClient
            from .store import Store

            self._client = ApiClient(self)
            self._client.set_store(Store.active())
            self._client.finished.connect(self._on_schema)
        self._pending_url = _key(resolve_vars(str(req.get("url") or ""), env))
        self.schema_btn.set_busy(True)
        self._client.send(req, settings, env)

    def _on_schema(self, resp) -> None:
        self.schema_btn.set_busy(False)
        if resp.error:
            self.notify.emit(i18n.tr("拉取 Schema 失败：") + i18n.tr(resp.error))
            return
        try:
            schema = gql.Schema(json.loads(resp.body.decode("utf-8", "replace")))
        except (ValueError, AttributeError, KeyError, TypeError) as exc:
            errs = gql.response_errors(resp.body)
            why = errs[0] if errs else (str(exc) or f"HTTP {resp.status}")
            self.notify.emit(i18n.tr("拉取 Schema 失败：") + why[:80])
            return
        _SCHEMAS[self._pending_url] = schema
        self._show_schema_info()
        q, m = schema.counts()
        self.notify.emit(i18n.trf("Schema 已就绪：{q} 个查询、{m} 个变更，输入即可补全", q=q, m=m))

    # -------------------------------------------------- 生成
    def _gen_menu(self) -> None:
        schema = self.schema()
        if schema is None:
            self.notify.emit(i18n.tr("先点「Schema」拉取结构，再从里面挑字段生成"))
            return
        t = theme()
        menu = Menu(self)
        acts = {}
        for kind in ("query", "mutation", "subscription"):
            fields = schema.fields(schema.roots.get(kind) or "")
            if not fields:
                continue
            head = menu.addAction(kind.upper())
            head.setEnabled(False)
            for name, f in list(fields.items())[:40]:
                act = menu.addAction(icons.icon("dot", t.text_faint, 10), f"{name}  {f['sig']}")
                acts[act] = (kind, name)
            menu.addSeparator()
        chosen = menu.exec(self.gen_btn.mapToGlobal(self.gen_btn.rect().bottomLeft()))
        if chosen not in acts:
            return
        kind, name = acts[chosen]
        text = gql.skeleton(schema, name, kind)
        cur = self.query.toPlainText().rstrip()
        self.query.setPlainText((cur + "\n\n" + text) if cur else text)
        ops = gql.operations(self.query.toPlainText())
        self._op = ops[-1] if ops else ""
        self._sync_vars()

    def _sync_vars(self) -> None:
        out = gql.sync_variables(self.query.toPlainText(), self.vars.toPlainText())
        if out != self.vars.toPlainText():
            self.vars.setPlainText(out)

    def _format(self) -> None:
        q = self.query.toPlainText()
        if q.strip() and not gql.check(q):
            self.query.setPlainText(gql.pretty(q).rstrip("\n"))
        v = self.vars.toPlainText().strip()
        if v:
            try:
                self.vars.setPlainText(json.dumps(json.loads(v), ensure_ascii=False, indent=2))
            except ValueError:
                pass

    # -------------------------------------------------- AI
    def _ai_write(self) -> None:
        from . import ai as ai_mod
        from .dialogs import PromptDialog

        ok, why = ai_mod.ready(ai_mod.config())
        if not ok:
            self.notify.emit(why)
            return
        dlg = PromptDialog(i18n.tr("AI 写查询"),
                           i18n.tr("想查什么？例如：id 为 1 的用户，带最近 5 个订单的金额"), "",
                           self.window())
        if not dlg.exec() or not dlg.value().strip():
            return
        schema = self.schema()
        msgs = ai_mod.messages_for_graphql(dlg.value(), schema.summary() if schema else "",
                                           self.query.toPlainText())
        self._ai_orig = self.query.toPlainText()
        self._ai_buf = ""
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("生成中…")
        self._chat = ai_mod.start(msgs, max_tokens=900, temperature=0.2,
                                  on_chunk=self._ai_chunk, on_done=self._ai_done,
                                  on_error=self._ai_error)

    def _ai_chunk(self, piece: str) -> None:
        self._ai_buf += piece

    def _ai_done(self, _full: str) -> None:
        from . import ai as ai_mod

        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("AI 写查询")
        text = ai_mod.clean_code(self._ai_buf)
        if not text.strip():
            self.notify.emit(i18n.tr("生成内容为空，换个说法再试"))
            return
        self.query.setPlainText(text)
        self._sync_vars()
        err = gql.check(text)
        self.notify.emit(i18n.tr("已生成查询，变量已补齐") if not err
                         else i18n.tr("生成的查询有问题：") + err)

    def _ai_error(self, message: str) -> None:
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("AI 写查询")
        self.notify.emit(message)
