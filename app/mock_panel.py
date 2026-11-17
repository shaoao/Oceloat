"""Mock 中心：本地 Mock 服务 + 公开接口 + 请求日志。

三个页签，各管一件事：
1. **本地 Mock** —— 在自己机器上起一个真的 HTTP 服务（127.0.0.1），
   路由、状态码、延迟、动态数据、条件规则、响应体全部自己定；
   前端、自动化脚本、另一台机器都能连。
2. **公开接口** —— 28 个免费公开 API，点一行就填好请求，用来验证网络与渲染。
3. **请求日志** —— 服务收到的每一次请求（方法 / 路径 / 状态 / 耗时 / 命中哪条规则），
   边调边看，不用去翻终端。

设计上保持「轻」：本地服务只用标准库，不写文件、不联网，关掉即释放。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .code_editor import CodeView
from .dialogs import GlassDialog
from .mock_server import DEFAULT_PORT, MockServer, default_routes, render_placeholders
from .theme import C, font, method_color, mono, theme
from .widgets import (
    Button,
    Card,
    ElideLabel,
    HBox,
    Label,
    Pill,
    SegmentedTabs,
    SmoothScrollArea,
    Switch,
    VBox,
    icon_button,
)

# ---------------------------------------------------------------- 公开接口清单
# (分组, 方法, 地址, 说明, 示例请求体)
MOCKS: List[Dict[str, Any]] = [
    # ---------------- 回显调试
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/get",
     "d": "回显请求头与查询参数，最稳的调试靶子"},
    {"g": "回显调试", "m": "POST", "u": "https://httpbin.org/post",
     "d": "回显 JSON 请求体", "b": '{"hello": "world"}'},
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/status/418",
     "d": "指定状态码，用来测错误分支与配色"},
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/delay/2",
     "d": "延迟 2 秒返回，看 loading 与超时设置"},
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/bytes/2048",
     "d": "2KB 随机字节，测二进制 / 十六进制预览"},
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/redirect/2",
     "d": "两次 302 跳转，验证跟随重定向开关"},
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/cookies/set?token=demo",
     "d": "服务端种 Cookie，用来测 Cookies 页与「从响应导入」"},
    {"g": "回显调试", "m": "GET", "u": "https://httpbin.org/stream/8",
     "d": "逐行输出 8 条 JSON，测流式响应"},
    {"g": "回显调试", "m": "POST", "u": "https://httpbin.org/anything",
     "d": "任意路径都会原样回显，适合乱试"},

    # ---------------- 假数据
    {"g": "假数据", "m": "GET", "u": "https://jsonplaceholder.typicode.com/posts",
     "d": "100 条文章，列表渲染的标准素材"},
    {"g": "假数据", "m": "GET", "u": "https://jsonplaceholder.typicode.com/posts/1",
     "d": "单条文章，字段少、结构清晰"},
    {"g": "假数据", "m": "GET", "u": "https://jsonplaceholder.typicode.com/comments?postId=1",
     "d": "带查询参数的评论列表"},
    {"g": "假数据", "m": "POST", "u": "https://jsonplaceholder.typicode.com/posts",
     "d": "创建资源（返回 201）", "b": '{"title": "Ocelot", "body": "hi", "userId": 1}'},
    {"g": "假数据", "m": "GET", "u": "https://dummyjson.com/products?limit=10",
     "d": "电商商品列表，字段更接近真实业务"},
    {"g": "假数据", "m": "GET", "u": "https://dummyjson.com/products/1",
     "d": "单个商品，含图片数组"},
    {"g": "假数据", "m": "GET", "u": "https://dummyjson.com/carts",
     "d": "购物车，嵌套结构，适合测树形视图"},
    {"g": "假数据", "m": "GET", "u": "https://dummyjson.com/posts/search?q=love",
     "d": "带搜索的列表，测参数联动"},
    {"g": "假数据", "m": "GET", "u": "https://dummyjson.com/http/500",
     "d": "强制 500，测失败提示"},

    # ---------------- 用户与登录
    {"g": "用户与登录", "m": "GET", "u": "https://reqres.in/api/users?page=2",
     "d": "分页用户列表（需带 x-api-key: reqres-free-v1）"},
    {"g": "用户与登录", "m": "POST", "u": "https://reqres.in/api/login",
     "d": "登录成功返回 token", "b": '{"email": "eve.holt@reqres.in", "password": "cityslicka"}'},
    {"g": "用户与登录", "m": "POST", "u": "https://reqres.in/api/login",
     "d": "缺字段 → 400，测参数校验", "b": '{"email": "eve.holt@reqres.in"}'},
    {"g": "用户与登录", "m": "POST", "u": "https://reqres.in/api/users",
     "d": "创建用户（201）", "b": '{"name": "Ocelot", "job": "api client"}'},
    {"g": "用户与登录", "m": "GET", "u": "https://randomuser.me/api/",
     "d": "随机一个人，含头像地址"},
    {"g": "用户与登录", "m": "GET", "u": "https://jsonplaceholder.typicode.com/users",
     "d": "10 个用户，含地址与公司"},

    # ---------------- 图片与文本
    {"g": "图片与文本", "m": "GET", "u": "https://dog.ceo/api/breeds/image/random",
     "d": "随机狗图（返回图片直链）"},
    {"g": "图片与文本", "m": "GET", "u": "https://picsum.photos/600/360",
     "d": "随机图片，直接测图片预览"},
    {"g": "图片与文本", "m": "GET", "u": "https://catfact.ninja/fact",
     "d": "一句猫知识，纯文本 JSON"},
    {"g": "图片与文本", "m": "GET", "u": "https://api.github.com/repos/qt/qtbase",
     "d": "GitHub 仓库信息，字段多、层级深"},
]

GROUPS = ["全部"] + sorted({m["g"] for m in MOCKS}, key=lambda g: [m["g"] for m in MOCKS].index(g))

PUBLIC_ROW_H = 46
METHOD_W = 46          # 方法列固定宽度：所有行的地址从同一条竖线开始
LIST_PAD = 14
META_W = 74            # 右侧「状态码 / 命中次数」列，行与行严格对齐

PLACEHOLDER_HINT = (
    "动态数据：{{@id}} {{@uuid}} {{@name}} {{@cname}} {{@email}} {{@phone}} "
    "{{@city}} {{@company}} {{@now}} {{@date}} {{@timestamp}} {{@bool}} "
    "{{@int(1,99)}} {{@float(1,999)}} {{@pick(a,b,c)}} {{@lorem(6)}} {{@avatar(80,80)}}"
)


# ---------------------------------------------------------------- 公开接口行


class MockRow(QWidget):
    """一行公开接口。文字全部交给子控件 + 布局排版，像素级对齐不再靠手算。"""

    clicked = pyqtSignal(dict)

    def __init__(self, item: Dict[str, Any], parent=None, show_group: bool = True):
        super().__init__(parent)
        self.item = item
        self._hover = False
        self.setFixedHeight(PUBLIC_ROW_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        t = theme()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(LIST_PAD, 5, LIST_PAD, 5)
        lay.setSpacing(10)

        method = (item["m"] or "GET").upper()
        tag = Label(method, 9.6, method_color(method, t), mono_font=True,
                    weight=QFont.Weight.DemiBold, spacing=0.3)
        tag.setFixedWidth(METHOD_W)
        tag.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)

        mid = VBox(ElideLabel(item["u"], 12.0, t.text),
                   ElideLabel(item["d"], 10.6, t.text_faint,
                              mode=Qt.TextElideMode.ElideRight),
                   spacing=2)
        mid.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(mid, 1)

        self.group_label: Optional[Label] = None
        if show_group:
            self.group_label = Label(item["g"], 9.4, t.text_faint, mono_font=True)
            lay.addWidget(self.group_label, 0, Qt.AlignmentFlag.AlignVCenter)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit(self.item)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        if not self._hover:
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.hover))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 2, -4, -2), 7, 7)
        p.end()


# ---------------------------------------------------------------- 本地路由行


class RouteRow(QWidget):
    """一行本地路由：方法 · 路径 / 名称+状态·延迟·规则·命中，右侧是复制、试用、编辑、删除。"""

    trial = pyqtSignal(dict)
    copy = pyqtSignal(dict)
    edit = pyqtSignal(dict)
    remove = pyqtSignal(dict)

    ROW_H = 52

    def __init__(self, item: Dict[str, Any], running: bool, parent=None, hits: int = 0):
        super().__init__(parent)
        self.item = item
        self._hover = False
        t = theme()
        self.setFixedHeight(self.ROW_H)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(LIST_PAD, 5, 8, 5)
        lay.setSpacing(10)

        method = (item.get("method") or "GET").upper()
        tag = Label("*" if method == "ANY" else method, 9.6, method_color(method, t),
                    mono_font=True, weight=QFont.Weight.DemiBold, spacing=0.3)
        tag.setFixedWidth(METHOD_W)
        lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)

        meta = f"{item.get('status', 200)}"
        if item.get("delay"):
            meta += f" · 延迟 {item['delay']}ms"
        if item.get("echo"):
            meta += " · 回显"
        rules = item.get("rules") or []
        if rules:
            meta += f" · {len(rules)} 条规则"
        mid = VBox(ElideLabel(item.get("path") or "/", 12.0, t.text, mono_font=True),
                   ElideLabel(f"{item.get('name') or '未命名'} · {meta}", 10.4, t.text_faint),
                   spacing=2)
        mid.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(mid, 1)

        self.hit_label = Label(f"{hits} 次" if hits else "", 10.2,
                               t.success if hits else t.text_faint, mono_font=True)
        self.hit_label.setFixedWidth(META_W)
        self.hit_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.hit_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.copy_btn = icon_button("copy", "复制完整地址", 22, 12)
        self.copy_btn.clicked.connect(lambda: self.copy.emit(self.item))
        self.trial_btn = icon_button("send", "用这条路由新建请求", 22, 12)
        self.trial_btn.clicked.connect(lambda: self.trial.emit(self.item))
        self.edit_btn = icon_button("pencil", "编辑", 22, 12)
        self.edit_btn.clicked.connect(lambda: self.edit.emit(self.item))
        self.del_btn = icon_button("trash", "删除", 22, 12)
        self.del_btn.clicked.connect(lambda: self.remove.emit(self.item))
        for b in (self.copy_btn, self.trial_btn, self.edit_btn, self.del_btn):
            b.setEnabled(running)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)

    def setup_buttons(self, running: bool) -> None:
        for b in (self.copy_btn, self.trial_btn):
            b.setEnabled(running)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.edit.emit(self.item)

    def paintEvent(self, _e):
        if not self._hover:
            return
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.hover))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 2, -4, -2), 7, 7)
        p.end()


# ---------------------------------------------------------------- 条件规则


def rule_summary(r: Dict[str, Any]) -> str:
    src = {"header": "请求头", "query": "查询参数", "body": "请求体",
           "method": "方法", "path": "路径"}.get((r.get("source") or "header").lower(), "请求头")
    op = {"eq": "等于", "contains": "包含", "exists": "存在", "missing": "不存在",
          "regex": "匹配正则", "startswith": "开头是", "gt": "大于", "lt": "小于"
          }.get((r.get("op") or "eq").lower(), "等于")
    key = r.get("key") or ""
    val = r.get("value") or ""
    cond = f"{src} {key} {op}" + (f" {val}" if val and op not in ("存在", "不存在") else "")
    out = f"{cond} → {r.get('status', 200)}"
    if r.get("delay"):
        out += f" · 延迟 {r['delay']}ms"
    return out


class RuleDialog(GlassDialog):
    """新建 / 编辑一条条件规则：满足条件时覆盖默认响应。"""

    def __init__(self, item: Optional[Dict[str, Any]] = None, parent=None):
        editing = item is not None
        super().__init__(parent, 620, 640, "编辑条件规则" if editing else "新建条件规则")
        self._src = dict(item or {})
        t = theme()

        body = QVBoxLayout(self.body)
        body.setContentsMargins(20, 10, 20, 16)
        body.setSpacing(12)

        self.name_edit = QLineEdit(self._src.get("name") or "")
        self.name_edit.setObjectName("Field")
        self.name_edit.setFixedHeight(30)
        self.name_edit.setPlaceholderText("例如：带 token 返回 VIP 数据")

        self.source_tabs = SegmentedTabs(
            [("header", "请求头"), ("query", "查询参数"), ("body", "请求体"), ("method", "方法")],
            style="pill", current=(self._src.get("source") or "header"), height=27,
            pad_h=10, font_size=11.2)
        self.op_tabs = SegmentedTabs(
            [("eq", "等于"), ("contains", "包含"), ("exists", "存在"), ("missing", "不存在")],
            style="pill", current=(self._src.get("op") or "eq"), height=27,
            pad_h=10, font_size=11.2)

        self.key_edit = QLineEdit(self._src.get("key") or "token")
        self.key_edit.setObjectName("Field")
        self.key_edit.setFixedHeight(30)
        self.key_edit.setFont(mono(11.8))
        self.value_edit = QLineEdit(self._src.get("value") or "")
        self.value_edit.setObjectName("Field")
        self.value_edit.setFixedHeight(30)
        self.value_edit.setFont(mono(11.8))

        self.status_edit = QLineEdit(str(self._src.get("status", 200)))
        self.status_edit.setObjectName("Field")
        self.status_edit.setFixedHeight(30)
        self.status_edit.setFixedWidth(76)
        self.status_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_edit.setFont(mono(11.8))
        self.delay_edit = QLineEdit(str(self._src.get("delay", 0)))
        self.delay_edit.setObjectName("Field")
        self.delay_edit.setFixedHeight(30)
        self.delay_edit.setFixedWidth(76)
        self.delay_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delay_edit.setFont(mono(11.8))

        body.addWidget(field("规则名称", self.name_edit, "只是给自己看的备注，可以空着"))
        body.addWidget(field("条件来源", HBox(self.source_tabs, 1)))
        pair = HBox((field("键", self.key_edit), 1), (field("值", self.value_edit), 1),
                    spacing=12)
        body.addWidget(pair)
        body.addWidget(field("比较方式", HBox(self.op_tabs, 1),
                             "「存在 / 不存在」不看值，只看有没有这个键"))
        body.addWidget(HBox(field("状态码", self.status_edit),
                            field("延迟（毫秒）", self.delay_edit), 1, spacing=12))

        head = HBox(Label("命中后的响应体", 10.4, t.text_dim, weight=QFont.Weight.DemiBold),
                    1, spacing=8)
        fmt = Button("格式化 JSON", None, kind="ghost", height=24, padding=8, font_size=10.8)
        fmt.clicked.connect(self._format)
        head.layout().addWidget(fmt)
        body.addWidget(head)

        editor_card = Card(radius=8)
        el = QVBoxLayout(editor_card)
        el.setContentsMargins(8, 8, 8, 8)
        el.setSpacing(4)
        self.body_view = CodeView(read_only=False, highlight=True, show_gutter=True)
        self.body_view.setFont(mono(11.4))
        self.body_view.setPlainText(self._src.get("body") or _rule_sample_body())
        self.body_view.setMinimumHeight(150)
        el.addWidget(self.body_view, 1)
        body.addWidget(editor_card, 1)
        hint = Label("留空表示沿用路由的默认响应体，只改状态码 / 延迟；"
                     "同样支持 {{@name}} 之类的动态占位符。", 10.4, t.text_faint)
        hint.setWordWrap(True)
        body.addWidget(hint)

        self.hint = Label("", 10.6, t.danger)
        body.addWidget(self.hint)

        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("保存", "check", kind="primary", height=28, padding=14, font_size=12)
        ok.clicked.connect(self._accept)
        body.addWidget(HBox(1, cancel, ok, spacing=6))

        self.source_tabs.changed.connect(lambda _k: self._sync())
        self.op_tabs.changed.connect(lambda _k: self._sync())
        self._sync()

    def _sync(self) -> None:
        src = self.source_tabs.current()
        op = self.op_tabs.current()
        self.key_edit.setEnabled(src != "method")
        self.key_edit.setPlaceholderText("body 支持 a.b.c 取嵌套字段" if src == "body" else "token")
        self.value_edit.setEnabled(op not in ("exists", "missing"))
        self.value_edit.setPlaceholderText("GET" if src == "method" else "要比对的值")

    def _format(self) -> None:
        try:
            data = json.loads(self.body_view.toPlainText() or "{}")
        except Exception:       # noqa: BLE001
            self.hint.setText("不是合法 JSON，没法格式化")
            return
        self.body_view.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        self.hint.setText("")

    def _accept(self) -> None:
        try:
            status = int(self.status_edit.text() or 200)
        except ValueError:
            self.hint.setText("状态码要填数字")
            return
        if not (100 <= status <= 599):
            self.hint.setText("状态码要在 100 ~ 599 之间")
            return
        try:
            delay = max(0, int(self.delay_edit.text() or 0))
        except ValueError:
            self.hint.setText("延迟要填数字（毫秒）")
            return
        key = (self.key_edit.text() or "").strip()
        if self.source_tabs.current() != "method" and not key:
            self.hint.setText("填一下要比对的键名")
            return
        self.result_item = {
            "id": self._src.get("id") or _new_id("r"),
            "name": (self.name_edit.text() or "").strip() or rule_summary({
                "source": self.source_tabs.current(), "op": self.op_tabs.current(),
                "key": key, "value": self.value_edit.text(), "status": status}),
            "source": self.source_tabs.current(),
            "op": self.op_tabs.current(),
            "key": key,
            "value": (self.value_edit.text() or "").strip(),
            "status": status,
            "delay": delay,
            "body": self.body_view.toPlainText(),
        }
        self.accept()


# ---------------------------------------------------------------- 路由编辑


class RouteDialog(GlassDialog):
    """新建 / 编辑一条 Mock 路由：基本信息 + 响应体 + 条件规则。"""

    def __init__(self, store, item: Optional[Dict[str, Any]] = None, parent=None):
        editing = item is not None
        super().__init__(parent, 660, 700, "编辑 Mock 路由" if editing else "新建 Mock 路由")
        self.store = store
        src = dict(item or {})
        self._echo = bool(src.get("echo"))
        self._rules: List[Dict[str, Any]] = [dict(r) for r in (src.get("rules") or [])]
        self._editing_id = src.get("id") or ""
        t = theme()

        body = QVBoxLayout(self.body)
        body.setContentsMargins(20, 10, 20, 14)
        body.setSpacing(11)

        self.name_edit = QLineEdit(src.get("name") or "新建路由")
        self.name_edit.setObjectName("Field")
        self.name_edit.setFixedHeight(30)

        self.method_tabs = SegmentedTabs(
            [("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("PATCH", "PATCH"),
             ("DELETE", "DELETE"), ("ANY", "任意")],
            style="pill", current=(src.get("method") or "GET").upper(),
            height=27, pad_h=10, font_size=11.2)
        self.method_tabs.set_current((src.get("method") or "GET").upper(), emit=False)

        self.path_edit = QLineEdit(src.get("path") or "/api/hello")
        self.path_edit.setObjectName("Field")
        self.path_edit.setFixedHeight(30)
        self.path_edit.setFont(mono(12))

        self.status_edit = QLineEdit(str(src.get("status", 200)))
        self.status_edit.setObjectName("Field")
        self.status_edit.setFixedHeight(30)
        self.status_edit.setFixedWidth(72)
        self.status_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_edit.setFont(mono(12))

        self.delay_edit = QLineEdit(str(src.get("delay", 0)))
        self.delay_edit.setObjectName("Field")
        self.delay_edit.setFixedHeight(30)
        self.delay_edit.setFixedWidth(72)
        self.delay_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delay_edit.setFont(mono(12))

        self.ctype_edit = QLineEdit(src.get("content_type") or "application/json")
        self.ctype_edit.setObjectName("Field")
        self.ctype_edit.setFixedHeight(30)
        self.ctype_edit.setFont(mono(11.5))

        body.addWidget(field("名称", self.name_edit, "列表里显示的名字，随便写"))
        body.addWidget(HBox(
            (field("方法", HBox(self.method_tabs, 1)), 0),
            (field("路径", self.path_edit, "以 / 开头；结尾 * 做前缀匹配"), 1),
            spacing=14))
        body.addWidget(HBox((field("状态码", self.status_edit), 0),
                            (field("延迟（毫秒）", self.delay_edit), 0),
                            (field("内容类型", self.ctype_edit), 1),
                            spacing=14))
        body.addWidget(Label("延迟到时间后才会返回，用来测 Loading、骨架屏与超时。",
                             10.2, t.text_faint))

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(Label("响应体", 10.4, t.text_dim, weight=QFont.Weight.DemiBold))
        hl.addStretch(1)
        self.echo_switch = Switch(self._echo)
        self.echo_switch.toggled.connect(self._on_echo)
        hl.addWidget(Label("回显请求", 10.8, t.text_faint))
        hl.addWidget(self.echo_switch)
        prev = Button("预览随机数据", "refresh", kind="ghost", height=24, padding=8,
                      font_size=10.8, icon_size=11)
        prev.clicked.connect(self._preview)
        hl.addWidget(prev)
        fmt = Button("格式化", None, kind="ghost", height=24, padding=8, font_size=10.8)
        fmt.clicked.connect(self._format)
        hl.addWidget(fmt)
        body.addWidget(head)

        editor_card = Card(radius=8)
        el = QVBoxLayout(editor_card)
        el.setContentsMargins(8, 8, 8, 8)
        el.setSpacing(5)
        self.body_view = CodeView(read_only=False, highlight=True, show_gutter=True)
        self.body_view.setFont(mono(11.4))
        self.body_view.setPlainText(src.get("body") or _sample_body())
        self.body_view.setMinimumHeight(120)
        el.addWidget(self.body_view, 1)
        self.echo_hint = Label(
            "回显模式：服务会把收到的请求（方法 / 路径 / 头 / 请求体）原样返回，"
            "下面的响应体不会生效。", 10.8, t.text_faint)
        self.echo_hint.setWordWrap(True)
        self.echo_hint.setVisible(False)
        el.addWidget(self.echo_hint)
        ph = Label(PLACEHOLDER_HINT, 10.2, t.text_faint, mono_font=True)
        ph.setWordWrap(True)
        el.addWidget(ph)
        body.addWidget(editor_card, 1)

        # ---------- 条件规则
        rhead = QWidget()
        rl = QHBoxLayout(rhead)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(Label("条件响应", 10.4, t.text_dim, weight=QFont.Weight.DemiBold))
        self.rule_count = Label("", 10.2, t.text_faint)
        rl.addWidget(self.rule_count)
        rl.addStretch(1)
        add_rule = Button("添加规则", "plus", kind="subtle", height=24, padding=9,
                          font_size=10.8, icon_size=11)
        add_rule.clicked.connect(self._add_rule)
        rl.addWidget(add_rule)
        body.addWidget(rhead)

        rules_card = Card(radius=8)
        rc = QVBoxLayout(rules_card)
        rc.setContentsMargins(2, 2, 2, 2)
        rc.setSpacing(0)
        self.rules_scroll = SmoothScrollArea()
        self.rules_scroll.setFixedHeight(96)
        holder = QWidget()
        self.rules_box = QVBoxLayout(holder)
        self.rules_box.setContentsMargins(0, 0, 0, 0)
        self.rules_box.setSpacing(0)
        self.rules_box.addStretch(1)
        self.rules_scroll.setWidget(holder)
        rc.addWidget(self.rules_scroll)
        self.rules_empty = Label(
            "还没有规则。例如「请求头 token 等于 123 → 200」，没带 token 时返回 401。",
            10.6, t.text_faint)
        self.rules_empty.setWordWrap(True)
        rc.addWidget(HBox(self.rules_empty, 1, margins=(12, 6, 12, 6)))
        body.addWidget(rules_card)

        self.hint = Label("", 10.6, t.danger)
        body.addWidget(self.hint)

        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("保存", "check", kind="primary", height=28, padding=14, font_size=12)
        ok.clicked.connect(self._accept)
        body.addWidget(HBox(1, cancel, ok, spacing=6))

        self._on_echo(self._echo)
        self._rebuild_rules()

    # -------------------------------------------------- 规则列表
    def _rebuild_rules(self) -> None:
        # 规则少的时候不要把 96px 的空盒子留在那里
        self.rules_scroll.setFixedHeight(min(max(len(self._rules) * 30, 30), 90))
        while self.rules_box.count() > 1:
            item = self.rules_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for i, r in enumerate(self._rules):
            row = RuleRow(r, rule_summary(r))
            row.edit.connect(lambda data: self._edit_rule(data))
            row.remove.connect(lambda data: self._remove_rule(data))
            self.rules_box.insertWidget(self.rules_box.count() - 1, row)
        self.rules_empty.setVisible(not self._rules)
        self.rules_scroll.setVisible(bool(self._rules))
        self.rule_count.setText(f"{len(self._rules)} 条" if self._rules else "")

    def _add_rule(self) -> None:
        dlg = RuleDialog(None, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._rules.append(dlg.result_item)
        self._rebuild_rules()

    def _edit_rule(self, data: Dict[str, Any]) -> None:
        dlg = RuleDialog(data, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        for i, r in enumerate(self._rules):
            if r.get("id") == data.get("id"):
                self._rules[i] = dlg.result_item
                break
        self._rebuild_rules()

    def _remove_rule(self, data: Dict[str, Any]) -> None:
        self._rules = [r for r in self._rules if r.get("id") != data.get("id")]
        self._rebuild_rules()

    # -------------------------------------------------- 其它
    def _on_echo(self, on: bool) -> None:
        self._echo = bool(on)
        self.body_view.setVisible(not on)
        self.echo_hint.setVisible(bool(on))

    def _preview(self) -> None:
        text = render_placeholders(self.body_view.toPlainText() or "")
        PreviewDialog(text, self).exec()

    def _format(self) -> None:
        try:
            data = json.loads(self.body_view.toPlainText() or "{}")
        except Exception:       # noqa: BLE001
            self.hint.setText("不是合法 JSON，没法格式化")
            return
        self.body_view.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
        self.body_view.set_language(None)
        self.hint.setText("")

    def _accept(self) -> None:
        path = (self.path_edit.text() or "").strip()
        if not path.startswith("/"):
            self.hint.setText("路径要以 / 开头")
            return
        try:
            status = int(self.status_edit.text() or 200)
        except ValueError:
            self.hint.setText("状态码要填数字")
            return
        if not (100 <= status <= 599):
            self.hint.setText("状态码要在 100 ~ 599 之间")
            return
        try:
            delay = max(0, int(self.delay_edit.text() or 0))
        except ValueError:
            self.hint.setText("延迟要填数字（毫秒）")
            return
        body = self.body_view.toPlainText()
        if not self._echo and body.strip() and "{{" not in body:
            try:
                json.loads(body)
            except Exception:   # noqa: BLE001 — 非 JSON 也允许，只是提醒
                self.hint.setText("提示：响应体不是合法 JSON，仍可保存")
        self.result_item = {
            "id": self._editing_id or _new_id("m"),
            "name": (self.name_edit.text() or "未命名").strip(),
            "method": self.method_tabs.current(),
            "path": path,
            "status": status,
            "delay": delay,
            "content_type": (self.ctype_edit.text() or "application/json").strip(),
            "body": "" if self._echo else body,
            "echo": self._echo,
            "enabled": True,
            "rules": self._rules,
        }
        self.accept()

    def _src_id(self) -> str:
        return self._editing_id

    def set_editing(self, item: Dict[str, Any]) -> None:
        self._editing_id = item.get("id") or ""


class RuleRow(QWidget):
    """条件规则的一行：摘要 + 编辑 / 删除。"""

    edit = pyqtSignal(dict)
    remove = pyqtSignal(dict)

    def __init__(self, item: Dict[str, Any], summary: str, parent=None):
        super().__init__(parent)
        self.item = item
        self._hover = False
        self.setFixedHeight(30)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        t = theme()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(8)
        lay.addWidget(Label(item.get("name") or summary, 11.2, t.text), 0)
        sub = ElideLabel(summary, 10.4, t.text_faint, mono_font=True)
        lay.addWidget(sub, 1)
        b1 = icon_button("pencil", "编辑规则", 20, 11)
        b1.clicked.connect(lambda: self.edit.emit(self.item))
        b2 = icon_button("trash", "删除规则", 20, 11)
        b2.clicked.connect(lambda: self.remove.emit(self.item))
        lay.addWidget(b1)
        lay.addWidget(b2)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(6, 1, -6, -1), 6, 6)
        else:
            p.setPen(C(t.border))
            p.drawLine(12, self.height() - 1, self.width() - 12, self.height() - 1)
        p.end()


class PreviewDialog(GlassDialog):
    """看一眼「动态数据」渲染出来的样子，确认占位符没写错。"""

    def __init__(self, text: str, parent=None):
        super().__init__(parent, 560, 420, "动态数据预览")
        from .markdown_view import CodeBlock

        body = QVBoxLayout(self.body)
        body.setContentsMargins(18, 10, 18, 14)
        body.setSpacing(8)
        tip = Label("每次请求都会重新生成，下面的值只是其中一次的结果。", 10.8,
                    theme().text_faint)
        tip.setWordWrap(True)
        body.addWidget(tip)
        body.addWidget(CodeBlock(text or "（空）", "json", max_height=260), 1)
        ok = Button("知道了", None, kind="primary", height=28, padding=16, font_size=12)
        ok.clicked.connect(self.accept)
        body.addWidget(HBox(1, ok, spacing=6))


def field(title: str, widget: QWidget, hint: str = "") -> QWidget:
    t = theme()
    parts = [Label(title, 10.4, t.text_dim, weight=QFont.Weight.DemiBold), widget]
    if hint:
        desc = Label(hint, 10.6, t.text_faint)
        desc.setWordWrap(True)
        parts.append(desc)
    return VBox(*parts, spacing=5)


def _new_id(prefix: str) -> str:
    import uuid

    return prefix + uuid.uuid4().hex[:8]


def _sample_body() -> str:
    return json.dumps({"code": 0, "message": "ok", "data": []}, ensure_ascii=False, indent=2)


def _rule_sample_body() -> str:
    return json.dumps({"code": 0, "vip": True, "data": {"plan": "enterprise"}},
                      ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 日志行


class LogRow(QWidget):
    """一条请求日志：时间 · 方法 · 路径 · 状态 · 耗时 · 命中。"""

    ROW_H = 30

    def __init__(self, entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        t = theme()
        self.setFixedHeight(self.ROW_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(LIST_PAD, 0, LIST_PAD, 0)
        lay.setSpacing(10)

        def cell(text: str, width: int, color: str, mono_font: bool = True,
                 align=None) -> Label:
            lab = Label(text, 10.8, color, mono_font=mono_font)
            lab.setFixedWidth(width)
            if align is not None:
                lab.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            return lab

        lay.addWidget(cell(entry.get("time", ""), 62, t.text_faint),
                      0, Qt.AlignmentFlag.AlignVCenter)
        status = int(entry.get("status") or 0)
        token = {2: t.success, 3: t.text_dim, 4: t.warning, 5: t.danger}.get(
            status // 100, t.text_dim)
        lay.addWidget(cell(entry.get("method", ""), 52, method_color(entry.get("method"), t)),
                      0, Qt.AlignmentFlag.AlignVCenter)
        path = ElideLabel(entry.get("path", ""), 11.2, t.text_dim, mono_font=True)
        lay.addWidget(path, 1)
        lay.addWidget(cell(str(status), 44, token, align=Qt.AlignmentFlag.AlignRight),
                      0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(cell(f"{entry.get('ms', 0)} ms", 66, t.text_faint,
                           align=Qt.AlignmentFlag.AlignRight),
                      0, Qt.AlignmentFlag.AlignVCenter)
        rule = entry.get("rule") or ""
        route = entry.get("route") or ""
        label = f"{route} · {rule}" if rule else route
        lay.addWidget(cell(label, 190, t.text_faint, mono_font=False,
                           align=Qt.AlignmentFlag.AlignRight),
                      0, Qt.AlignmentFlag.AlignVCenter)


# ---------------------------------------------------------------- 主对话框


class MockDialog(GlassDialog):
    """Mock 中心：本地服务 / 公开接口 / 请求日志。"""

    chosen = pyqtSignal(dict)                 # 选了一个公开接口
    trialRequested = pyqtSignal(str, str)     # (method, url) 直接把请求发出去前先建好请求

    def __init__(self, store, server: Optional[MockServer] = None, parent=None):
        super().__init__(parent, 940, 660, "Mock 中心")
        self.store = store
        self.server = server or MockServer()
        self._owns_server = server is None
        self._query = ""
        self._group = "全部"
        self.rows: List[MockRow] = []
        self.route_rows: List[RouteRow] = []
        self.log_rows: List[LogRow] = []
        self._log_fp: tuple = ()
        t = theme()

        body = QVBoxLayout(self.body)
        body.setContentsMargins(16, 8, 16, 12)
        body.setSpacing(10)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        self.tabs = SegmentedTabs(
            [("local", "本地 Mock"), ("public", "公开接口"), ("logs", "请求日志")],
            style="pill", current="local", height=28, pad_h=13, font_size=11.8)
        self.tabs.changed.connect(self._on_tab)
        hl.addWidget(self.tabs)
        hl.addStretch(1)
        self.hint = Label("", 10.6, t.text_faint)
        hl.addWidget(self.hint)
        body.addWidget(head)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_local())
        self.stack.addWidget(self._page_public())
        self.stack.addWidget(self._page_logs())
        body.addWidget(self.stack, 1)
        self._sync_local(rebuild=True)

        self.log_timer = QTimer(self)
        self.log_timer.setInterval(900)
        self.log_timer.timeout.connect(self._refresh_logs)

    # -------------------------------------------------- 本地 Mock 页
    def _page_local(self) -> QWidget:
        t = theme()
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        card = Card(radius=10)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 12, 10)
        cl.setSpacing(6)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)
        self.status_pill = Pill("未启动", t.text_faint, font_size=9.8)
        tl.addWidget(self.status_pill)
        tl.addWidget(Label("本地 Mock 服务", 12.6, t.text, weight=QFont.Weight.DemiBold))
        self.base_label = ElideLabel("http://127.0.0.1:%d" % DEFAULT_PORT, 11.2, t.text_faint,
                                     mono_font=True)
        tl.addWidget(self.base_label, 1)
        tl.addWidget(Label("端口", 10.6, t.text_faint))
        self.port_edit = QLineEdit(str(self._cfg().get("port") or DEFAULT_PORT))
        self.port_edit.setObjectName("Field")
        self.port_edit.setFixedHeight(26)
        self.port_edit.setFixedWidth(62)
        self.port_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.port_edit.setFont(mono(11.5))
        tl.addWidget(self.port_edit)
        self.start_btn = Button("启动服务", "play", kind="primary", height=26, padding=12,
                                font_size=11.6, icon_size=12)
        self.start_btn.clicked.connect(self._toggle)
        tl.addWidget(self.start_btn)
        cl.addWidget(top)

        self.local_hint = Label("", 10.6, t.text_faint)
        self.local_hint.setWordWrap(True)
        cl.addWidget(self.local_hint)

        self.scroll = SmoothScrollArea()
        holder = QWidget()
        self.routes_box = QVBoxLayout(holder)
        self.routes_box.setContentsMargins(0, 2, 0, 2)
        self.routes_box.setSpacing(0)
        self.routes_box.addStretch(1)
        self.scroll.setWidget(holder)
        cl.addWidget(self.scroll, 1)

        empty = Label("还没有路由。点下面的「新建路由」，写个 /api/hello 试试。",
                      11.4, t.text_faint)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label = empty
        cl.addWidget(empty)
        cl.addWidget(Label(
            "路径末尾写 * 做前缀匹配（/api/users/*）；没匹配上的请求返回 404，"
            "并列出当前全部可用路由。响应体支持动态占位符与条件规则。",
            10.4, t.text_faint))
        lay.addWidget(card, 1)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(2, 0, 2, 0)
        fl.setSpacing(10)
        add = Button("新建路由", "plus", kind="subtle", height=28, padding=12, font_size=11.8,
                     icon_size=12)
        add.clicked.connect(self._add_route)
        copy_base = Button("复制地址", "copy", kind="ghost", height=28, padding=10,
                           font_size=11.6, icon_size=12)
        copy_base.clicked.connect(self._copy_base)
        fl.addWidget(add)
        fl.addWidget(copy_base)
        fl.addStretch(1)
        self.fallback_switch = Switch(bool(self._cfg().get("fallback_echo", False)))
        self.fallback_switch.toggled.connect(self._on_fallback)
        fl.addWidget(Label("无匹配时回显请求", 10.8, t.text_faint))
        fl.addWidget(self.fallback_switch)
        self.auto_switch = Switch(bool(self._cfg().get("auto_start", False)))
        self.auto_switch.toggled.connect(self._on_auto)
        fl.addWidget(Label("随应用启动", 10.8, t.text_faint))
        fl.addWidget(self.auto_switch)
        lay.addWidget(foot)
        return page

    LEGACY_ROUTES = {"示例 · 用户信息", "示例 · 回显请求", "示例 · 服务异常"}

    def _cfg(self) -> Dict[str, Any]:
        cfg = self.store.data.setdefault("mock", {})
        cfg.setdefault("port", DEFAULT_PORT)
        routes = cfg.get("routes")
        # 老版本只有三条示例：新版本把动态数据 / 条件规则 / 延迟做成示例，
        # 只有「完全没动过那三条」时才替换，用户自己改过的路由一条都不碰
        if routes and {r.get("name") for r in routes} == self.LEGACY_ROUTES \
                and not any(r.get("rules") for r in routes):
            cfg["routes"] = default_routes()
        cfg.setdefault("routes", default_routes())
        cfg.setdefault("fallback_echo", False)
        cfg.setdefault("auto_start", False)
        return cfg

    # 启动 / 停止
    def _toggle(self) -> None:
        if self.server.running:
            self._stop()
        else:
            self._start()

    def _start(self) -> bool:
        cfg = self._cfg()
        try:
            port = int(self.port_edit.text() or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        ok, msg = self.server.start(cfg.get("routes") or [], port,
                                    bool(cfg.get("fallback_echo")))
        if ok:
            cfg["port"] = port
            self.store.save()
            self.port_edit.setText(str(self.server.port))
            note = msg if msg.startswith("端口") else ""
            self.local_hint.setText(
                (note + "。" if note else "") +
                f"服务运行中：{self.server.base} —— 本机浏览器、脚本、别的设备都能连。")
        else:
            self.local_hint.setText(msg)
        self._sync_local(rebuild=True)
        return ok

    def _stop(self) -> None:
        port = self.server.port
        self.server.stop()
        # 停完再确认一次端口真的关了：否则界面说「已停止」，浏览器还能连上
        if port and self.server.port_in_use(port):
            self.local_hint.setText(
                f"已停止本地服务，但端口 {port} 仍被其它程序占用（可能是另一个 Ocelot 实例）。")
        else:
            self.local_hint.setText("服务已停止。已经填好的路由仍然保留，重启后继续用。")
        self._sync_local(rebuild=True)

    def _sync_local(self, rebuild: bool = False) -> None:
        t = theme()
        running = self.server.running
        self.status_pill.set_text("运行中" if running else "未启动")
        self.status_pill.set_color(t.success if running else t.text_faint)
        # 按钮必须跟着真实状态走：之前固定写成「停止服务」，没启动时点一下等于什么也没做
        self.start_btn.setText("停止服务" if running else "启动服务")
        self.start_btn.set_icon("stop" if running else "play")
        self.start_btn.set_kind("subtle" if running else "primary")
        self.base_label.setText(self.server.base if running
                               else f"http://127.0.0.1:{self.port_edit.text() or DEFAULT_PORT}")
        self.port_edit.setEnabled(not running)
        if running:
            if not self.local_hint.text() or "已停止" in self.local_hint.text():
                self.local_hint.setText(f"服务运行中：{self.server.base} —— "
                                        "本机任何工具都能连这个地址。")
        else:
            if not self.local_hint.text() or "运行中" in self.local_hint.text():
                self.local_hint.setText("启动后：请求发到 http://127.0.0.1:<端口>/<路径>，"
                                        "本机的浏览器、脚本、别的设备都能连。")
            self._check_port_owner()
        for row in self.route_rows:
            row.setup_buttons(running)
        if rebuild:
            self._rebuild_routes()

    def _check_port_owner(self) -> None:
        """没启动却有人在这个端口应答时，明确告诉用户是谁 —— 不要装作没这回事。"""
        try:
            port = int(self.port_edit.text() or DEFAULT_PORT)
        except ValueError:
            return
        if not self.server.port_in_use(port):
            return
        if MockServer._probe_ocelot(port):
            self.local_hint.setText(
                f"端口 {port} 上已经有一个 Ocelot Mock 服务在响（可能是另一次启动的 Ocelot，"
                "或上次没有正常退出）。要接管请先在那边停止，或直接点「启动服务」，会自动换端口。")
        else:
            self.local_hint.setText(
                f"端口 {port} 已被其它程序占用。点「启动服务」会自动挑一个空闲端口，"
                "实际地址会显示在这里。")

    def _rebuild_routes(self) -> None:
        while self.routes_box.count() > 1:
            item = self.routes_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.route_rows.clear()
        routes = self._cfg().get("routes") or []
        hits = getattr(self.server, "hits", {}) or {}
        for r in routes:
            row = RouteRow(r, self.server.running, hits=int(hits.get(r.get("name") or "", 0)))
            row.edit.connect(self._edit_route)
            row.remove.connect(self._remove_route)
            row.copy.connect(self._copy_route)
            row.trial.connect(self._trial_route)
            self.route_rows.append(row)
            self.routes_box.insertWidget(self.routes_box.count() - 1, row)
        self.empty_label.setVisible(not routes)
        self.scroll.setVisible(bool(routes))
        self.hint.setText(
            i18n.tr("{n} 条路由").format(n=len(routes)) if self.tabs.current() == "local" else "")

    def _add_route(self) -> None:
        dlg = RouteDialog(self.store, None, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._cfg()["routes"].append(dlg.result_item)
        self.store.save()
        self._rebuild_routes()
        self._restart_if_running()

    def _edit_route(self, item: Dict[str, Any]) -> None:
        dlg = RouteDialog(self.store, item, self)
        dlg.set_editing(item)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        routes = self._cfg()["routes"]
        for i, r in enumerate(routes):
            if r.get("id") == item.get("id"):
                routes[i] = dlg.result_item
                break
        self.store.save()
        self._rebuild_routes()
        self._restart_if_running()

    def _remove_route(self, item: Dict[str, Any]) -> None:
        routes = self._cfg()["routes"]
        self.store.data["mock"]["routes"] = [r for r in routes if r.get("id") != item.get("id")]
        self.store.save()
        self._rebuild_routes()
        self._restart_if_running()

    def _copy_route(self, item: Dict[str, Any]) -> None:
        from PyQt6.QtGui import QGuiApplication

        if not self.server.running:
            self.local_hint.setText("先启动服务，才有地址可复制")
            return
        QGuiApplication.clipboard().setText(self.server.url_for(item.get("path") or "/"))
        self.local_hint.setText(f"已复制 {item.get('path')}")

    def _trial_route(self, item: Dict[str, Any]) -> None:
        if not self.server.running:
            self.local_hint.setText("先启动服务，再试用这条路由")
            return
        self.trialRequested.emit((item.get("method") or "GET").upper(),
                                 self.server.url_for(item.get("path") or "/"))
        self.accept()

    def _copy_base(self) -> None:
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(self.server.base if self.server.running
                                            else self.base_label.text())
        self.local_hint.setText("根地址已复制")

    def _on_fallback(self, on: bool) -> None:
        self._cfg()["fallback_echo"] = bool(on)
        self.store.save()
        self._restart_if_running()

    def _on_auto(self, on: bool) -> None:
        self._cfg()["auto_start"] = bool(on)
        self.store.save()

    def _restart_if_running(self) -> None:
        if self.server.running:
            self._start()
            self._sync_local(rebuild=True)

    # -------------------------------------------------- 公开接口页
    def _page_public(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("Field")
        self.search.setPlaceholderText("搜索接口、域名或用途，例如 登录 / json / 图片")
        self.search.setFont(font(12.5))
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._on_search)
        lay.addWidget(self.search)

        self.group_tabs = SegmentedTabs([(g, g) for g in GROUPS], style="pill",
                                        current="全部", height=28, pad_h=11, font_size=11.6)
        self.group_tabs.changed.connect(self._on_group)
        lay.addWidget(HBox(self.group_tabs, 1))

        card = Card(radius=10)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(2, 4, 2, 4)
        self.public_scroll = SmoothScrollArea()
        holder = QWidget()
        self.rows_box = QVBoxLayout(holder)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(0)
        self.rows_box.addStretch(1)
        self.public_scroll.setWidget(holder)
        cl.addWidget(self.public_scroll)
        lay.addWidget(card, 1)

        return page

    def _on_tab(self, key: str) -> None:
        self.stack.setCurrentIndex({"local": 0, "public": 1, "logs": 2}.get(key, 0))
        if key == "local":
            self._sync_local()
            self.hint.setText(
                i18n.tr("{n} 条路由").format(n=len(self._cfg().get("routes") or [])))
        elif key == "logs":
            self._refresh_logs(force=True)
            self.log_timer.start()
        else:
            self.log_timer.stop()
            self._rebuild_public()

    def _on_search(self, text: str) -> None:
        """输入防抖：每敲一个字就重建 28 行控件会明显掉帧，攒 120ms 再重建。"""
        self._query = (text or "").strip().lower()
        timer = getattr(self, "_search_timer", None)
        if timer is None:
            timer = self._search_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(120)
            timer.timeout.connect(self._rebuild_public)
        timer.start()

    def _on_group(self, key: str) -> None:
        self._group = key
        self._rebuild_public()

    def _visible(self) -> List[Dict[str, Any]]:
        out = []
        for item in MOCKS:
            if self._group != "全部" and item["g"] != self._group:
                continue
            if self._query:
                blob = f"{item['u']} {item['d']} {item['m']}".lower()
                if self._query not in blob:
                    continue
            out.append(item)
        return out

    def _rebuild_public(self) -> None:
        while self.rows_box.count() > 1:
            item = self.rows_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.rows.clear()
        items = self._visible()
        for item in items:
            row = MockRow(item, show_group=(self._group == "全部"))
            row.clicked.connect(self._pick)
            self.rows.append(row)
            self.rows_box.insertWidget(self.rows_box.count() - 1, row)
        if not items:
            empty = Label("没有匹配的接口，换个关键词试试", 12, theme().text_faint)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setFixedHeight(120)
            self.rows_box.insertWidget(0, empty)
        self.hint.setText(f"{len(items)} 个公开接口 · 点一行新建请求")

    def _pick(self, item: Dict[str, Any]) -> None:
        self.chosen.emit(item)
        self.accept()

    # -------------------------------------------------- 请求日志页
    def _page_logs(self) -> QWidget:
        t = theme()
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(2, 0, 2, 0)
        bl.setSpacing(10)
        self.log_stats = Label("", 10.8, t.text_faint, mono_font=True)
        bl.addWidget(self.log_stats)
        bl.addStretch(1)
        reload_btn = Button("刷新", "refresh", kind="ghost", height=26, padding=10,
                            font_size=11.2, icon_size=11)
        reload_btn.clicked.connect(lambda: self._refresh_logs(force=True))
        clear_btn = Button("清空", "trash", kind="ghost", height=26, padding=10,
                           font_size=11.2, icon_size=11)
        clear_btn.clicked.connect(self._clear_logs)
        bl.addWidget(reload_btn)
        bl.addWidget(clear_btn)
        lay.addWidget(bar)

        card = Card(radius=10)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(2, 4, 2, 4)
        self.log_scroll = SmoothScrollArea()
        holder = QWidget()
        self.logs_box = QVBoxLayout(holder)
        self.logs_box.setContentsMargins(0, 0, 0, 0)
        self.logs_box.setSpacing(0)
        self.logs_box.addStretch(1)
        self.log_scroll.setWidget(holder)
        cl.addWidget(self.log_scroll)
        self.logs_empty = Label(
            i18n.tr("还没有请求。启动本地服务后，任何打到它的请求都会出现在这里 —— "
                    "包括方法、路径、状态码、耗时，以及命中了哪条规则。"),
            11.2, t.text_faint)
        self.logs_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logs_empty.setWordWrap(True)
        cl.addWidget(self.logs_empty)
        lay.addWidget(card, 1)
        return page

    def _clear_logs(self) -> None:
        self.server.clear_logs()
        self._refresh_logs(force=True)

    def _refresh_logs(self, force: bool = False) -> None:
        entries = list(getattr(self.server, "logs", []) or [])
        fp = (len(entries), entries[0].get("time") if entries else "",
              entries[0].get("path") if entries else "", entries[0].get("ms") if entries else 0)
        if not force and fp == self._log_fp:
            return
        self._log_fp = fp

        while self.logs_box.count() > 1:
            item = self.logs_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.log_rows.clear()
        for entry in entries[:120]:
            row = LogRow(entry)
            self.log_rows.append(row)
            self.logs_box.insertWidget(self.logs_box.count() - 1, row)
        self.logs_empty.setVisible(not entries)
        self.log_scroll.setVisible(bool(entries))
        self.log_stats.setText(self._log_summary(entries))

    @staticmethod
    def _log_summary(entries: List[Dict[str, Any]]) -> str:
        if not entries:
            return i18n.tr("还没有请求")
        ok = sum(1 for e in entries if 200 <= int(e.get("status") or 0) < 300)
        bad = sum(1 for e in entries if int(e.get("status") or 0) >= 400)
        avg = int(sum(int(e.get("ms") or 0) for e in entries) / len(entries))
        return (f"{i18n.tr('共')} {len(entries)} {i18n.tr('次')} · 2xx {ok} · "
                f"4xx/5xx {bad} · {i18n.tr('平均')} {avg} ms · "
                f"{i18n.tr('最近一条')} {entries[0].get('time', '')}")

    # -------------------------------------------------- 生命周期
    def showEvent(self, e):
        super().showEvent(e)
        self._sync_local(rebuild=True)
        self._refresh_logs(force=True)
        if self.tabs.current() == "logs":
            self.log_timer.start()
        if len(self._cfg().get("routes") or []) == 0:
            self._cfg()["routes"] = default_routes()
            self._rebuild_routes()

    def closeEvent(self, e):
        self.log_timer.stop()
        if self._owns_server:
            self.server.stop()
        super().closeEvent(e)
