"""Mock 服务：本地 Mock 服务 + 公开接口 + 请求日志。

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

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons, mock_ai, mock_import, qr
from .code_editor import CodeView
from .dialogs import GlassDialog, Menu
from .mock_server import (
    DEFAULT_PORT,
    MockHub,
    MockServer,
    mock_config,
    render_placeholders,
)
from .theme import C, font, method_color, mono, theme, ui_scale
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
    "{{@id}} {{@name}} {{@cname}} {{@email}} {{@float(1,999)}} {{@now}} …"
    "｜多条数据 {{for size}}…{{/for}}｜分页 {{@page}} {{@size}} {{@row}}"
)
# 悬浮/展开时才需要看的完整说明：放在 tooltip 里，不占编辑区高度
PLACEHOLDER_HELP = (
    "随机字段：{{@id}} {{@uuid}} {{@name}} {{@cname}} {{@email}} {{@phone}} "
    "{{@city}} {{@company}} {{@now}} {{@date}} {{@timestamp}} {{@bool}} "
    "{{@int(1,99)}} {{@float(1,999)}} {{@pick(a,b,c)}} {{@lorem(6)}} {{@avatar(80,80)}}\n\n"
    "多条数据：\n"
    "  \"list\": [{{for size}}{\"id\": {{@row}}, \"name\": \"{{@cname}}\"}{{/for}}]\n"
    "{{for size}} 按 ?size= 展开；循环里 {{@i}} 是本次第几条，{{@row}} 是跨页连续行号。\n\n"
    "分页：{{@page}} 当前页、{{@size}} 每页条数、{{@total(86)}} 总数；"
    "请求带 ?page=2&size=20 就返回第二页。"
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

    def __init__(self, item: Dict[str, Any], running: bool, parent=None, hits: int = 0,
                 indent: int = 0):
        super().__init__(parent)
        self.item = item
        self._hover = False
        t = theme()
        self.setFixedHeight(self.ROW_H)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(LIST_PAD + 14 * indent, 5, 8, 5)
        lay.setSpacing(10)

        method = (item.get("method") or "GET").upper()
        tag = Label("*" if method == "ANY" else method, 9.6, method_color(method, t),
                    mono_font=True, weight=QFont.Weight.DemiBold, spacing=0.3)
        tag.setFixedWidth(METHOD_W)
        lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)

        meta = f"{item.get('status', 200)}"
        if item.get("delay"):
            meta += " · " + i18n.trf("延迟 {ms}ms", ms=item["delay"])
        if item.get("echo"):
            meta += " · " + i18n.tr("回显")
        rules = item.get("rules") or []
        if rules:
            meta += " · " + i18n.trf("{n} 条规则", n=len(rules))
        name = i18n.tr(item.get("name") or "未命名")
        mid = VBox(ElideLabel(item.get("path") or "/", 12.0, t.text, mono_font=True),
                   ElideLabel(f"{name} · {meta}", 10.4, t.text_faint),
                   spacing=2)
        mid.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(mid, 1)

        self.hit_label = Label(i18n.trf("{n} 次", n=hits) if hits else "", 10.2,
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
    cond = f"{src} {key} {i18n.tr(op)}" + (f" {val}" if val and op not in ("存在", "不存在") else "")
    out = f"{cond} → {r.get('status', 200)}"
    if r.get("delay"):
        out += " · " + i18n.trf("延迟 {ms}ms", ms=r["delay"])
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
        i18n.placeholder(self.name_edit, "例如：带 token 返回 VIP 数据")

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
        i18n.placeholder(self.key_edit,
                             "body 支持 a.b.c 取嵌套字段" if src == "body" else "token")
        self.value_edit.setEnabled(op not in ("exists", "missing"))
        i18n.placeholder(self.value_edit, "GET" if src == "method" else "要比对的值")

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


class BodyAiDialog(GlassDialog):
    """AI 生成响应体：一句话 → 一段带循环 / 分页的模板。

    故意做小（560×430）：它只是「往里填一段文本」的小工具，不开大窗、不铺
    全屏遮罩。常用例子做成一行小按钮，点一下就填好描述，省得用户自己组织语言。
    """

    def __init__(self, path: str = "", method: str = "GET", body: str = "", parent=None):
        super().__init__(parent, 580, 470, "AI 生成响应体")
        t = theme()
        self._path = path
        self._method = method
        self._body = body
        self._buf = ""
        self._chat = None
        self.result = ""

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 8, 18, 14)
        lay.setSpacing(9)

        self.desc = QLineEdit()
        self.desc.setObjectName("Field")
        self.desc.setFixedHeight(30)
        i18n.placeholder(self.desc, "例如：分页的商品列表，带价格、状态和创建时间")
        self.desc.returnPressed.connect(self._go)
        lay.addWidget(self.desc)

        lay.addWidget(Label("常用例子", 10.2, t.text_faint))
        grid = QWidget()
        gl = QVBoxLayout(grid)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(5)
        btns = []
        for label, prompt in mock_ai.BODY_PRESETS:
            btn = Button(label, None, kind="subtle", height=23, padding=9, font_size=10.6)
            btn.setToolTip(prompt)
            btn.clicked.connect(lambda _c=False, p=prompt: self.desc.setText(p))
            btns.append(btn)
        for i in range(0, len(btns), 3):
            row = HBox(*btns[i:i + 3], 1, spacing=5)
            gl.addWidget(row)
        lay.addWidget(grid)

        self.out = CodeView(read_only=True, highlight=True, show_gutter=False)
        self.out.setFont(mono(11))
        self.out.setPlaceholderText(i18n.tr("生成的响应体会显示在这里；点「生成」开始。"))
        card = Card(radius=8)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.addWidget(self.out)
        lay.addWidget(card, 1)

        self.status = Label("", 10.4, t.text_faint)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        self.go = Button("生成", "spark", kind="primary", height=28, padding=16,
                         font_size=12, icon_size=12)
        self.go.clicked.connect(self._go)
        self.ok = Button("插入", "check", kind="primary", height=28, padding=14, font_size=12)
        self.ok.clicked.connect(self.accept)
        self.ok.setEnabled(False)
        lay.addWidget(HBox(1, cancel, self.ok, self.go, spacing=6))

    def _go(self) -> None:
        from . import ai

        ok, why = ai.ready()
        if not ok:
            self.status.setText(why)
            self.status.setStyleSheet(f"color: {theme().danger};")
            return
        text = (self.desc.text() or "").strip()
        if not text:
            self.status.setText(i18n.tr("先用一句话说清楚要什么数据"))
            return
        self._buf = ""
        self.out.setPlainText("")
        self.status.setText(i18n.tr("生成中…"))
        self.status.setStyleSheet(f"color: {theme().text_faint};")
        self.go.setEnabled(False)
        self.ok.setEnabled(False)
        self._chat = ai.start(mock_ai.messages_for_body(text, self._path, self._method, self._body),
                              on_chunk=self._chunk, on_done=self._done, on_error=self._fail)

    def _chunk(self, piece: str) -> None:
        self._buf += piece
        self.out.setPlainText(self._buf)
        bar = self.out.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _done(self, _text: str) -> None:
        self.go.setEnabled(True)
        try:
            self.result = mock_ai.parse_body(self._buf)
        except ValueError as exc:
            self.status.setText(str(exc))
            self.status.setStyleSheet(f"color: {theme().danger};")
            return
        self.out.setPlainText(self.result)
        self.status.setText(i18n.tr("可以直接插入；想微调就在编辑器里改。"))
        self.status.setStyleSheet(f"color: {theme().success};")
        self.ok.setEnabled(True)

    def _fail(self, msg: str) -> None:
        self.go.setEnabled(True)
        self.status.setText(msg)
        self.status.setStyleSheet(f"color: {theme().danger};")

    def closeEvent(self, e):  # noqa: N802
        chat = self._chat
        if chat is not None and chat.isRunning():
            try:
                chat.cancel()
            except Exception:      # noqa: BLE001
                pass
        super().closeEvent(e)


class RouteDialog(GlassDialog):
    """新建 / 编辑一条 Mock 路由：基本信息 + 响应体 + 条件规则。"""

    def __init__(self, store, item: Optional[Dict[str, Any]] = None, parent=None):
        editing = item is not None
        super().__init__(parent, 680, 762, "编辑 Mock 路由" if editing else "新建 Mock 路由")
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
        # AI 生成：一句话写清楚要什么数据，直接产出带循环 / 分页的模板
        ai_btn = Button("AI 生成", "spark", kind="subtle", height=24, padding=9,
                        font_size=10.8, icon_size=11)
        ai_btn.setToolTip("用一句话描述数据，让 AI 写出带循环与分页的响应体")
        ai_btn.clicked.connect(self._ai_body)
        hl.addWidget(ai_btn)
        # 例子：不联网也能用的模板片段，点一下插到光标处
        ex_btn = Button("例子", None, kind="ghost", height=24, padding=8, font_size=10.8)
        ex_btn.clicked.connect(lambda: self._examples(ex_btn))
        hl.addWidget(ex_btn)
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
        self.body_view.setMinimumHeight(112)
        el.addWidget(self.body_view, 1)
        self.echo_hint = Label(
            "回显模式：服务会把收到的请求（方法 / 路径 / 头 / 请求体）原样返回，"
            "下面的响应体不会生效。", 10.8, t.text_faint)
        self.echo_hint.setWordWrap(True)
        self.echo_hint.setVisible(False)
        el.addWidget(self.echo_hint)
        # 一行、按宽度省略：完整语法放 tooltip，编辑区的高度全留给响应体本身
        ph = ElideLabel(PLACEHOLDER_HINT, 9.8, t.text_faint, mono_font=True,
                        mode=Qt.TextElideMode.ElideRight)
        ph.setFixedHeight(15)
        ph.setToolTip(PLACEHOLDER_HELP)
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
        # 预览时按「第一页、5 条」展开，分页占位符也能看到真实效果
        text = render_placeholders(self.body_view.toPlainText() or "", {"page": 1, "size": 5})
        PreviewDialog(text, self).exec()

    def _ai_body(self) -> None:
        """AI 生成响应体：生成期间不影响编辑器，插入是显式动作。"""
        dlg = BodyAiDialog(self.path_edit.text().strip(),
                           self.method_tabs.current(),
                           self.body_view.toPlainText() or "", self)
        if dlg.exec() != dlg.DialogCode.Accepted or not dlg.result.strip():
            return
        self.body_view.setPlainText(dlg.result)
        self.body_view.set_language(None)
        self.hint.setText(i18n.tr("已插入 AI 生成的响应体，可以点「预览随机数据」看看效果"))

    def _examples(self, anchor: QWidget) -> None:
        menu = Menu(self)
        actions = []
        for label, snippet in mock_ai.BODY_SNIPPETS:
            actions.append((menu.addAction(label), snippet))
        chosen = menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        for act, snippet in actions:
            if chosen is act:
                self.body_view.insertPlainText(snippet)
                self.body_view.set_language(None)
                self.hint.setText("")
                return

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


def _fmt_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1048576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


# 自绘行里字体 / 度量各建一次就够：以前每次 paintEvent、每一列都 new 一个 QFont，
# 滚动几百行时光是建对象就够呛。缓存按 (字号, 等宽, 缩放比) 分桶，改缩放自动失效。
_FONTS: Dict[tuple, QFont] = {}
_FMS: Dict[tuple, QFontMetricsF] = {}


def _f(size: float, is_mono: bool = True,
       weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    key = (size, is_mono, int(weight), round(ui_scale(), 3))
    f = _FONTS.get(key)
    if f is None:
        f = _FONTS[key] = (mono(size, weight) if is_mono else font(size, weight))
    return f


def _fm(size: float, is_mono: bool = True,
        weight: QFont.Weight = QFont.Weight.Normal) -> QFontMetricsF:
    key = (size, is_mono, int(weight), round(ui_scale(), 3))
    m = _FMS.get(key)
    if m is None:
        m = _FMS[key] = QFontMetricsF(_f(size, is_mono, weight))
    return m


_PIX: Dict[tuple, Any] = {}


def _icon(name: str, color: str, size: int, weight: float = 1.5):
    """分组行的折叠箭头 / 文件夹图标：滚动时每帧都重画会不停新建位图，缓存住。"""
    key = (name, color, size, weight)
    pm = _PIX.get(key)
    if pm is None:
        pm = _PIX[key] = icons.pixmap(name, color, size, weight)
    return pm


class LogRow(QWidget):
    """一条请求日志：时间 · 方法 · 路径 · 状态 · 耗时 · 体积 · 来源 · 命中。

    整行自己画，不放子控件：日志最多 300 条，一行 8 个 QLabel 就是两千多个控件，
    滚动时全在重排；自己画只有一次 paintEvent，快得多，也不会出现
    「最后一列被挤出窗口」这种布局问题。
    """

    ROW_H = 30
    COLS = (  # (右边距起算的宽度, 对齐) —— 从右往左排，路径吃掉剩下的宽度
        ("route", 150),
        ("client", 92),
        ("size", 52),
        ("ms", 60),
        ("status", 38),
    )
    GAP = 10
    TIME_W = 66
    METHOD_W = 50

    def __init__(self, entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setFixedHeight(self.ROW_H)

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        e = self.entry
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w = self.width()

        p.setPen(QPen(C(t.border)))
        p.drawLine(LIST_PAD, self.height() - 1, w - LIST_PAD, self.height() - 1)

        # 右侧固定列
        x = w - LIST_PAD
        status = int(e.get("status") or 0)
        token = {2: t.success, 3: t.text_dim, 4: t.warning, 5: t.danger}.get(
            status // 100, t.text_dim)
        values = {
            "route": (e.get("route") or "") +
                     (f" · {e['rule']}" if e.get("rule") else ""),
            "client": e.get("client") or "-",
            "size": _fmt_size(int(e.get("size") or 0)),
            "ms": f"{e.get('ms', 0)} ms",
            "status": str(status),
        }
        colors = {"status": token, "route": t.text_faint, "client": t.text_faint,
                  "size": t.text_faint, "ms": t.text_faint}
        for key, cw in self.COLS:
            x -= cw
            p.setPen(C(colors[key]))
            text = values[key]
            rect = QRectF(x, 0, cw, self.height())
            if key == "route":
                p.setFont(_f(11.0, False))
                text = _fm(11.0, False).elidedText(text, Qt.TextElideMode.ElideRight, cw)
                p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft |
                                     Qt.AlignmentFlag.AlignVCenter), text)
            else:
                p.drawText(rect, int(Qt.AlignmentFlag.AlignRight |
                                     Qt.AlignmentFlag.AlignVCenter), text)
            x -= self.GAP
        path_right = x
        if not values["route"]:
            path_right = w - LIST_PAD

        # 左侧固定列
        p.setFont(_f(10.4))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(LIST_PAD, 0, self.TIME_W, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   str(e.get("time", "")))
        mx = LIST_PAD + self.TIME_W + self.GAP
        p.setPen(C(method_color(e.get("method"), t)))
        p.drawText(QRectF(mx, 0, self.METHOD_W, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   str(e.get("method", "")))

        # 中间路径：吃掉剩余空间，超长右省略
        px = mx + self.METHOD_W + self.GAP
        avail = max(24.0, path_right - px)
        p.setFont(_f(11.0))
        p.setPen(C(t.text_dim))
        shown = _fm(11.0).elidedText(i18n.tr(str(e.get("path", ""))),
                                     Qt.TextElideMode.ElideRight, avail)
        p.drawText(QRectF(px, 0, avail, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), shown)
        p.end()


# ---------------------------------------------------------------- 主对话框


# ---------------------------------------------------------------- 分组树


def _ensure_groups(routes: List[Dict[str, Any]]) -> None:
    """补齐老数据缺的字段：id / group / enabled。"""
    for r in routes:
        if not r.get("id"):
            r["id"] = _new_id("m")
        if not r.get("group") and str(r.get("name") or "").startswith("示例"):
            r["group"] = "示例"
        r.setdefault("group", "")
        r.setdefault("enabled", True)
        r.setdefault("rules", [])


class GroupRow(QWidget):
    """树里的一个分组标题：折叠箭头 + 名字 + 条数。点击折叠，右键出菜单。"""

    toggled = pyqtSignal(str)
    menuRequested = pyqtSignal(str, object)

    H = 32

    def __init__(self, prefix: str, label: str, count: int, depth: int,
                 collapsed: bool, parent=None):
        super().__init__(parent)
        self.prefix = prefix
        self.label = label
        self.count = count
        self.depth = depth
        self.collapsed = collapsed
        self._hover = False
        self.setFixedHeight(self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip(i18n.trf("{name} · {n} 条路由 · 右键可重命名", name=prefix, n=count))

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.toggled.emit(self.prefix)
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):  # noqa: N802
        self.menuRequested.emit(self.prefix, e.globalPos())

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(4, 2, -4, -2), 6, 6)
        x = LIST_PAD + 14 * self.depth
        chev = _icon("chevron_right" if self.collapsed else "chevron_down",
                     t.text_faint, 11, 1.7)
        p.drawPixmap(QPointF(x, (self.height() - 11) / 2), chev)
        x += 15
        folder = _icon("folder", t.text_faint, 13, 1.5)
        p.drawPixmap(QPointF(x, (self.height() - 13) / 2), folder)
        x += 19
        p.setFont(_f(11.8, False, QFont.Weight.DemiBold))
        p.setPen(C(t.text_dim))
        p.drawText(QRectF(x, 0, self.width() - x - 40, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.label)
        x += _fm(11.8, False, QFont.Weight.DemiBold).horizontalAdvance(self.label) + 7
        p.setFont(_f(9.8))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(x, 0, 40, self.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   str(self.count))
        p.end()


# ---------------------------------------------------------------- 小工具弹窗


class TextPromptDialog(GlassDialog):
    """一个输入框的轻量弹窗：建分组、重命名、改名字都用它。"""

    def __init__(self, title: str, label: str, value: str = "", hint: str = "",
                 parent=None, width: int = 460):
        super().__init__(parent, width, 214, title)
        t = theme()
        self._value = value
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(20, 12, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(Label(label, 11.2, t.text_dim, weight=QFont.Weight.DemiBold))
        self.edit = QLineEdit(value)
        self.edit.setObjectName("Field")
        self.edit.setFixedHeight(30)
        self.edit.setFont(mono(12))
        self.edit.returnPressed.connect(self._accept)
        lay.addWidget(self.edit)
        if hint:
            h = Label(hint, 10.4, t.text_faint)
            h.setWordWrap(True)
            lay.addWidget(h)
        lay.addStretch(1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("确定", "check", kind="primary", height=28, padding=14, font_size=12)
        ok.clicked.connect(self._accept)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        QTimer.singleShot(0, self.edit.setFocus)

    def _accept(self) -> None:
        self._value = self.edit.text().strip()
        if self._value:
            self.accept()

    def value(self) -> str:
        return self._value


class NewInstanceDialog(GlassDialog):
    """新建一个 Mock 实例：名字 + 端口，端口冲突会自动顺延。"""

    def __init__(self, ports: List[int], parent=None):
        super().__init__(parent, 480, 268, "新建 Mock 实例")
        t = theme()
        suggest = (max(ports) + 1) if ports else DEFAULT_PORT
        while suggest in ports:
            suggest += 1
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(20, 12, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(Label("实例名称", 11.2, t.text_dim, weight=QFont.Weight.DemiBold))
        self.name = QLineEdit(i18n.trf("服务 {n}", n=len(ports) + 1))
        self.name.setObjectName("Field")
        self.name.setFixedHeight(30)
        lay.addWidget(self.name)
        lay.addWidget(Label("端口", 11.2, t.text_dim, weight=QFont.Weight.DemiBold))
        self.port = QLineEdit(str(suggest))
        self.port.setObjectName("Field")
        self.port.setFixedHeight(30)
        self.port.setFixedWidth(110)
        self.port.setFont(mono(12))
        lay.addWidget(self.port)
        hint = Label("每个实例是一个独立的 HTTP 服务，端口不同；可以同时启动，"
                     "用来模拟「订单服务 + 商品服务」这种互相调用的场景。",
                     10.4, t.text_faint)
        hint.setWordWrap(True)
        lay.addWidget(hint, 1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("创建", "plus", kind="primary", height=28, padding=14, font_size=12)
        ok.clicked.connect(self._accept)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))

    def _accept(self) -> None:
        name = (self.name.text() or "").strip()
        try:
            port = int(self.port.text() or DEFAULT_PORT)
        except ValueError:
            return
        if not name:
            return
        self.result_item = {"name": name, "port": max(0, min(port, 65535))}
        self.accept()


class ScenarioDialog(GlassDialog):
    """场景管理：预置四种常用故障态，也支持按路由自定义覆盖。"""

    PRESETS = [
        ("normal", "正常", "所有路由按原样返回"),
        ("unauth", "鉴权失败", "全部路由返回 401，body 为统一错误"),
        ("slow", "慢接口", "每条路由额外延迟 2000ms"),
        ("down", "服务不可用", "全部路由返回 503"),
        ("empty", "空数据", "响应体统一变成空数组"),
    ]

    def __init__(self, scenarios: List[Dict[str, Any]], active: str, parent=None):
        super().__init__(parent, 560, 420, "Mock 场景")
        self.result_item = None
        self._scenarios = [dict(s) for s in (scenarios or []) if isinstance(s, dict)]
        self._active = active or ""
        t = theme()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 12, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(Label("选择场景，切换后服务里的路由会立刻按新规则返回。",
                            11, t.text_faint))
        self.preset_tabs = SegmentedTabs(
            [(k, label) for k, label, _desc in self.PRESETS],
            style="pill", height=27, font_size=11.2, pad_h=10)
        self.preset_tabs.set_current("normal", emit=False)
        lay.addWidget(self.preset_tabs)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("Field")
        self.name_edit.setFixedHeight(30)
        i18n.placeholder(self.name_edit, "场景名称（可改）")
        lay.addWidget(self.name_edit)
        self.desc = Label("", 10.6, t.text_faint)
        self.desc.setWordWrap(True)
        lay.addWidget(self.desc)
        self.apply_btn = Button("应用并保存", "check", kind="primary", height=28,
                                padding=14, font_size=12)
        self.apply_btn.clicked.connect(self._apply)
        self.preset_tabs.changed.connect(self._on_preset)
        self._on_preset("normal")
        lay.addWidget(HBox(1, self.apply_btn, spacing=6))

    def _on_preset(self, key: str) -> None:
        preset = next((p for p in self.PRESETS if p[0] == key), None)
        self.desc.setText(i18n.tr(preset[2]) if preset else "")
        found = next((s for s in self._scenarios if s.get("id") == key), None)
        self.name_edit.setText(i18n.tr(found.get("name")) if found else
                               i18n.tr(preset[1]) if preset else "")

    def _apply(self) -> None:
        key = self.preset_tabs.current()
        name = (self.name_edit.text() or "").strip() or i18n.tr("未命名场景")
        overrides: Dict[str, Any] = {}
        if key == "unauth":
            overrides = {"*": {"status": 401, "body": '{"error":"unauthorized"}'}}
        elif key == "slow":
            overrides = {"*": {"delay": 2000}}
        elif key == "down":
            overrides = {"*": {"status": 503, "body": '{"error":"service unavailable"}'}}
        elif key == "empty":
            overrides = {"*": {"status": 200, "body": "[]"}}
        self.result_item = {
            "id": key, "name": name, "overrides": overrides,
            "builtin": True,
        }
        self.accept()


class LanQrDialog(GlassDialog):
    """局域网调试：把当前实例的地址画成二维码，手机扫一下就能连。"""

    def __init__(self, server: MockServer, parent=None):
        super().__init__(parent, 520, 560, "手机调试 · 局域网")
        t = theme()
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(22, 12, 22, 18)
        lay.setSpacing(12)

        nets = server.lan_urls()
        target = nets[0] if nets else (server.base if server.running else "")
        lay.addWidget(Label(i18n.tr("用手机扫这个码，就能直接访问当前 Mock 服务。"),
                            11.4, t.text_dim))

        card = Card(radius=12)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(18, 18, 18, 18)
        cl.setSpacing(10)
        pic = QLabel()
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if target:
            pic.setPixmap(qr.pixmap(target, 196, fg="#111111" if not t.is_dark else "#111111",
                                    bg="#FFFFFF"))
        else:
            pic.setText(i18n.tr("服务还没启动"))
            pic.setStyleSheet(f"color: {t.text_faint};")
        cl.addWidget(pic)
        url = Label(target or "—", 12.5, t.text, mono_font=True)
        url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(url)
        cl.addWidget(Label(i18n.tr("手机与电脑要连同一个 Wi-Fi"), 10.4, t.text_faint))
        lay.addWidget(card)

        rows = [("localhost", server.base if server.running else "")]
        for addr in nets:
            rows.append((i18n.tr("局域网"), addr))
        for name, addr in rows:
            if not addr:
                continue
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 0, 2, 0)
            rl.setSpacing(8)
            rl.addWidget(Label(name, 10.4, t.text_faint, mono_font=True))
            rl.addWidget(ElideLabel(addr, 11.6, t.text_dim, mono_font=True), 1)
            btn = Button("复制", "copy", kind="ghost", height=24, padding=9, font_size=10.8,
                         icon_size=11)
            btn.clicked.connect(lambda _c=False, a=addr: self._copy(a))
            rl.addWidget(btn)
            lay.addWidget(row)

        if server.running and not server.lan:
            warn = Label(i18n.tr("当前只监听本机。打开上面的「局域网」开关重启服务后，"
                                 "手机才能访问；访问不到时检查系统防火墙是否放行该端口。"),
                         10.4, t.warning)
            warn.setWordWrap(True)
            lay.addWidget(warn)
        lay.addStretch(1)
        ok = Button("关闭", None, kind="primary", height=28, padding=20, font_size=12)
        ok.clicked.connect(self.accept)
        lay.addWidget(HBox(1, ok, spacing=6))

    @staticmethod
    def _copy(text: str) -> None:
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text)


class MockAiDialog(GlassDialog):
    """AI 生成 Mock：一句话描述业务，生成一组路由；或者给现有路由生成测试用例。"""

    MODES = [("routes", "生成接口"), ("cases", "生成用例")]

    def __init__(self, routes: List[Dict[str, Any]], parent=None):
        super().__init__(parent, 720, 620, "AI 生成 Mock")
        t = theme()
        self.routes = routes
        self.result_routes: List[Dict[str, Any]] = []
        self.result_cases: List[Dict[str, Any]] = []
        self._buf = ""
        self._chat = None

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(20, 10, 20, 16)
        lay.setSpacing(10)

        self.mode = SegmentedTabs(self.MODES, style="pill", current="routes", height=27,
                                  pad_h=12, font_size=11.6)
        self.mode.changed.connect(self._sync)
        lay.addWidget(HBox(self.mode, 1))

        self.desc = QLineEdit()
        self.desc.setObjectName("Field")
        self.desc.setFixedHeight(30)
        i18n.placeholder(self.desc, "例如：一个博客系统，有文章列表、详情、发布、删除")
        self.desc.returnPressed.connect(self._go)
        lay.addWidget(self.desc)

        self.note = Label("", 10.4, t.text_faint)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

        self.out = CodeView(read_only=True, highlight=True, show_gutter=False)
        self.out.setFont(mono(11))
        self.out.setPlaceholderText(
            i18n.tr("生成的路由会显示在这里；点右下角「生成」开始。"))
        card = Card(radius=8)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.addWidget(self.out)
        lay.addWidget(card, 1)

        self.status = Label("", 10.6, t.text_faint)
        lay.addWidget(self.status)

        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        self.go = Button("生成", "spark", kind="primary", height=28, padding=16,
                         font_size=12, icon_size=12)
        self.go.clicked.connect(self._go)
        self.ok = Button("插入", "check", kind="primary", height=28, padding=14, font_size=12)
        self.ok.clicked.connect(self.accept)
        self.ok.setEnabled(False)
        lay.addWidget(HBox(1, cancel, self.ok, self.go, spacing=6))

        self._sync("routes")

    # -------------------------------------------------- 交互
    def _sync(self, key: str) -> None:
        cases = key == "cases"
        i18n.placeholder(self.desc, "补充要求（可留空），例如：多加几个鉴权失败的用例"
                         if cases else
                         "例如：一个博客系统，有文章列表、详情、发布、删除")
        if cases and self.routes:
            self.note.setText(i18n.trf("将基于当前实例的 {n} 条路由生成用例（正常 / 参数缺失 / "
                                       "边界 / 鉴权失败）。", n=len(self.routes)))
        else:
            self.note.setText(i18n.tr("AI 会直接生成可用的路由与响应体，插到当前实例里；"
                                      "Key 在「设置 → AI」里配置。"))
        self.result_routes = []
        self.result_cases = []
        self.ok.setEnabled(False)

    def _go(self) -> None:
        from . import ai

        cfg = ai.config()
        ok, why = ai.ready(cfg)
        if not ok:
            self.status.setText(why)
            self.status.setStyleSheet(f"color: {theme().danger};")
            return
        text = (self.desc.text() or "").strip()
        mode = self.mode.current()
        if mode == "routes" and not text:
            self.status.setText(i18n.tr("先用一句话说清楚要做什么"))
            return
        if mode == "cases" and not self.routes:
            self.status.setText(i18n.tr("先有路由，AI 才能针对它们生成用例"))
            return
        msgs = (mock_ai.messages_for_cases(self.routes, text) if mode == "cases"
                else mock_ai.messages_for_routes(text, 6, self.routes))
        self._buf = ""
        self.out.setPlainText("")
        self.status.setText(i18n.tr("生成中…"))
        self.status.setStyleSheet(f"color: {theme().text_faint};")
        self.go.setEnabled(False)
        self.ok.setEnabled(False)
        self._chat = ai.start(msgs, on_chunk=self._chunk, on_done=self._done,
                              on_error=self._fail)

    def _chunk(self, piece: str) -> None:
        self._buf += piece
        self.out.setPlainText(self._buf)
        bar = self.out.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _done(self, _text: str) -> None:
        self.go.setEnabled(True)
        mode = self.mode.current()
        try:
            if mode == "cases":
                self.result_cases = mock_ai.parse_cases(self._buf)
                self.out.setPlainText("\n".join(
                    f"{c['method']} {c['path']}  →  {c['expect_status']}  {c['name']}"
                    for c in self.result_cases))
                self.status.setText(i18n.trf("生成了 {n} 条用例", n=len(self.result_cases)))
            else:
                self.result_routes = mock_ai.parse_routes(self._buf)
                self.out.setPlainText(json.dumps(
                    [{k: r[k] for k in ("name", "group", "method", "path", "status")}
                     for r in self.result_routes], ensure_ascii=False, indent=2))
                self.status.setText(i18n.trf("生成了 {n} 条路由", n=len(self.result_routes)))
            self.status.setStyleSheet(f"color: {theme().success};")
            self.ok.setEnabled(True)
        except ValueError as exc:
            self.status.setText(str(exc))
            self.status.setStyleSheet(f"color: {theme().danger};")

    def _fail(self, msg: str) -> None:
        self.go.setEnabled(True)
        self.status.setText(msg)
        self.status.setStyleSheet(f"color: {theme().danger};")

    def closeEvent(self, e):  # noqa: N802
        chat = self._chat
        if chat is not None and chat.isRunning():
            try:
                chat.cancel()
            except Exception:      # noqa: BLE001
                pass
        super().closeEvent(e)


class CasesDialog(GlassDialog):
    """测试用例清单：每条都能复制成 curl，拿去终端或 CI 里跑。"""

    def __init__(self, cases: List[Dict[str, Any]], base: str, parent=None):
        super().__init__(parent, 780, 600, "Mock 测试用例")
        t = theme()
        self.cases = cases
        self.base = base
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(8)

        head = HBox(Label(i18n.trf("{n} 条用例 · 点右侧复制成 cURL", n=len(cases)), 10.8,
                          t.text_faint), 1, spacing=8)
        head.layout().setContentsMargins(2, 0, 2, 0)
        copy_all = Button("全部复制", "copy", kind="ghost", height=26, padding=10,
                          font_size=11.2, icon_size=11)
        copy_all.clicked.connect(self._copy_all)
        head.layout().addWidget(copy_all)
        lay.addWidget(head)

        card = Card(radius=10)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(2, 4, 2, 4)
        self.scroll = SmoothScrollArea()
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        for case in cases:
            box.addWidget(self._row(case))
        box.addStretch(1)
        self.scroll.setWidget(holder)
        cl.addWidget(self.scroll)
        lay.addWidget(card, 1)
        ok = Button("关闭", None, kind="primary", height=28, padding=20, font_size=12)
        ok.clicked.connect(self.accept)
        lay.addWidget(HBox(1, ok, spacing=6))

    def _row(self, case: Dict[str, Any]) -> QWidget:
        t = theme()
        row = QWidget()
        row.setFixedHeight(46)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(LIST_PAD, 4, LIST_PAD, 4)
        rl.setSpacing(10)
        status = Label(str(case.get("expect_status")), 10, t.success, mono_font=True,
                       weight=QFont.Weight.DemiBold)
        status.setFixedWidth(34)
        rl.addWidget(status)
        method = Label(case.get("method", "GET"), 9.6, method_color(case.get("method", "GET"), t),
                       mono_font=True, weight=QFont.Weight.DemiBold)
        method.setFixedWidth(METHOD_W)
        rl.addWidget(method)
        mid = VBox(ElideLabel(case.get("path", "/"), 11.8, t.text, mono_font=True),
                   ElideLabel(f"{case.get('name', '')} · {case.get('note', '')}", 10.4,
                              t.text_faint), spacing=1)
        mid.layout().setContentsMargins(0, 0, 0, 0)
        rl.addWidget(mid, 1)
        btn = icon_button("copy", "复制为 cURL", 22, 12)
        btn.clicked.connect(lambda _c=False, c=case: self._copy(mock_ai.case_as_curl(c, self.base)))
        rl.addWidget(btn)
        return row

    def _copy(self, text: str) -> None:
        from PyQt6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text)

    def _copy_all(self) -> None:
        self._copy("\n\n".join(mock_ai.case_as_curl(c, self.base) for c in self.cases))


# ---------------------------------------------------------------- 主对话框


class MockDialog(GlassDialog):
    """Mock 中心：本地服务（可多实例）/ 公开接口 / 请求日志。

    这是个独立窗口，不是模态弹窗：开着它照样能切请求、发请求、改路由 ——
    调 Mock 的时候本来就要一边看服务一边改主界面。
    """

    MODELESS = True

    chosen = pyqtSignal(dict)                 # 选了一个公开接口
    trialRequested = pyqtSignal(str, str)     # (method, url)
    stateChanged = pyqtSignal()               # 启停后通知主窗口刷新状态徽章

    def __init__(self, store, server: Optional[MockHub] = None, parent=None):
        super().__init__(parent, 960, 690, "Mock 服务")
        self.store = store
        if isinstance(server, MockHub):
            self.hub = server
        else:
            self.hub = MockHub()
            if server is not None:            # 兼容只传单个 MockServer 的旧调用
                self.hub.attach(server)
        self._query = ""
        self._group = "全部"
        self._collapsed: set = set()
        self.rows: List[MockRow] = []
        self.route_rows: List[RouteRow] = []
        self.log_rows: List[LogRow] = []
        self._log_keys: List[int] = []
        self._chat = None
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

    # -------------------------------------------------- 配置
    def _cfg(self) -> Dict[str, Any]:
        return mock_config(self.store.data)

    def _instances(self) -> List[Dict[str, Any]]:
        return self._cfg()["instances"]

    def _current(self) -> Dict[str, Any]:
        insts = self._instances()
        iid = getattr(self, "_instance", "main")
        for inst in insts:
            if inst.get("id") == iid:
                return inst
        self._instance = insts[0].get("id", "main")
        return insts[0]

    def _srv(self) -> MockServer:
        inst = self._current()
        return self.hub.get(inst.get("id") or "main", inst.get("name") or "")

    def _routes(self) -> List[Dict[str, Any]]:
        return self._current().setdefault("routes", [])

    # -------------------------------------------------- 本地 Mock 页
    def _page_local(self) -> QWidget:
        t = theme()
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)

        card = Card(radius=10)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 12, 10)
        cl.setSpacing(6)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(7)
        self.status_pill = Pill("未启动", t.text_faint, font_size=9.8)
        tl.addWidget(self.status_pill)
        self.inst_tabs = SegmentedTabs([("main", "默认实例")], style="pill",
                                       current="main", height=26, pad_h=10, font_size=11.2)
        self.inst_tabs.changed.connect(self._switch_instance)
        tl.addWidget(self.inst_tabs)
        self.inst_more = icon_button("more", "实例管理", 24, 13)
        self.inst_more.clicked.connect(self._instance_menu)
        tl.addWidget(self.inst_more)
        tl.addStretch(1)
        self.port_edit = QLineEdit(str(self._current().get("port") or DEFAULT_PORT))
        self.port_edit.setObjectName("Field")
        self.port_edit.setFixedHeight(26)
        self.port_edit.setFixedWidth(58)
        self.port_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.port_edit.setFont(mono(11.5))
        self.port_edit.setToolTip(i18n.tr("服务端口"))
        tl.addWidget(self.port_edit)
        self.lan_switch = Switch(bool(self._current().get("lan")))
        self.lan_switch.toggled.connect(self._on_lan)
        lan_box = QWidget()
        lan_box.setFixedHeight(26)
        lan_l = QHBoxLayout(lan_box)
        lan_l.setContentsMargins(0, 0, 0, 0)
        lan_l.setSpacing(6)
        lan_l.addWidget(Label("局域网", 10.6, t.text_faint), 0,
                        Qt.AlignmentFlag.AlignVCenter)
        lan_l.addWidget(self.lan_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        lan_box.setToolTip("打开后监听 0.0.0.0，手机 / 其它电脑可以用局域网 IP 访问")
        tl.addWidget(lan_box, 0, Qt.AlignmentFlag.AlignVCenter)
        # 只有开了局域网才有可扫的地址，没开就不占宽度
        self.qr_btn = Button("扫码", "external", kind="ghost", height=26, padding=10,
                             font_size=11.4, icon_size=11, tooltip="手机上打开二维码")
        self.qr_btn.clicked.connect(self._show_qr)
        tl.addWidget(self.qr_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        # 加进布局的顺序要在 setVisible 之前：addWidget 会把子控件重新 show 出来
        self.qr_btn.setVisible(bool(self._current().get("lan")))
        self.start_btn = Button("启动服务", "play", kind="primary", height=26, padding=12,
                                font_size=11.6, icon_size=12)
        self.start_btn.clicked.connect(self._toggle)
        tl.addWidget(self.start_btn)
        cl.addWidget(top)

        base_row = QWidget()
        brl = QHBoxLayout(base_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.setSpacing(8)
        self.base_label = ElideLabel("http://127.0.0.1:%d" % DEFAULT_PORT, 11.2, t.text_faint,
                                     mono_font=True, mode=Qt.TextElideMode.ElideRight)
        brl.addWidget(self.base_label, 1)
        copy_base = Button("复制地址", "copy", kind="ghost", height=22, padding=8,
                           font_size=10.6, icon_size=11)
        copy_base.clicked.connect(self._copy_base)
        brl.addWidget(copy_base)
        cl.addWidget(base_row)

        self.local_hint = Label("", 10.5, t.text_faint)
        self.local_hint.setWordWrap(True)
        cl.addWidget(self.local_hint)

        tools = QWidget()
        tool_l = QHBoxLayout(tools)
        tool_l.setContentsMargins(0, 0, 0, 0)
        tool_l.setSpacing(6)
        for text, icon, slot in (
            ("新建路由", "plus", self._add_route),
            ("新建分组", "folder", self._new_group),
            ("导入 OpenAPI / Postman", "transfer", self._import_doc),
            ("AI 生成", "spark", self._ai_generate),
        ):
            b = Button(text, icon, kind="subtle", height=26, padding=10, font_size=11.2,
                       icon_size=11)
            b.clicked.connect(slot)
            tool_l.addWidget(b)
        tool_l.addStretch(1)
        self.scenario_btn = Button("场景：正常", "layers", kind="ghost", height=26,
                                   padding=10, font_size=11.2,
                                   tooltip="一键切换 Mock 场景：正常 / 鉴权失败 / 慢接口 / 服务不可用")
        self.scenario_btn.clicked.connect(self._on_scenario)
        tool_l.addWidget(self.scenario_btn)
        self.fallback_switch = Switch(bool(self._cfg().get("fallback_echo", False)))
        self.fallback_switch.toggled.connect(self._on_fallback)
        tool_l.addWidget(Label("无匹配时回显", 10.6, t.text_faint))
        tool_l.addWidget(self.fallback_switch)
        cl.addWidget(tools)

        self.scroll = SmoothScrollArea()
        holder = QWidget()
        self.routes_box = QVBoxLayout(holder)
        self.routes_box.setContentsMargins(0, 2, 0, 2)
        self.routes_box.setSpacing(0)
        self.routes_box.addStretch(1)
        self.scroll.setWidget(holder)
        cl.addWidget(self.scroll, 1)

        empty = Label("还没有路由。点「新建路由」写个 /api/hello，"
                      "或者直接导入现成的 OpenAPI / Postman 文件。", 11.4, t.text_faint)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.empty_label = empty
        cl.addWidget(empty)
        tip = Label("路径末尾写 * 做前缀匹配（/api/users/*）；没匹配上的请求返回 404，"
                    "并列出当前全部可用路由。响应体支持 {{@name}} 动态占位符与条件规则。",
                    10.3, t.text_faint)
        tip.setWordWrap(True)
        cl.addWidget(tip)
        lay.addWidget(card, 1)
        return page

    # -------------------------------------------------- 实例
    def _sync_instance_tabs(self) -> None:
        insts = self._instances()
        items = [(i.get("id") or "main", i.get("name") or "实例") for i in insts]
        self.inst_tabs.set_items(items, current=self._current().get("id") or "main")
        # 只有一个实例时不必占地方
        self.inst_tabs.setVisible(len(items) > 1)

    def _switch_instance(self, iid: str) -> None:
        if iid == self._current().get("id"):
            return
        self._instance = iid
        inst = self._current()
        self.port_edit.setText(str(inst.get("port") or DEFAULT_PORT))
        self.lan_switch.setChecked(bool(inst.get("lan")))
        self.qr_btn.setVisible(bool(inst.get("lan")))
        self._sync_scenario_label()
        self._sync_local(rebuild=True)

    def _instance_menu(self) -> None:
        t = theme()
        menu = Menu(self)
        a_new = menu.addAction(icons.icon("plus", t.text, 14), i18n.tr("新建实例…"))
        a_rename = menu.addAction(icons.icon("pencil", t.text, 14), i18n.tr("重命名当前实例…"))
        a_del = menu.addAction(icons.icon("trash", t.text, 14), i18n.tr("删除当前实例…"))
        for inst in self._instances():
            mark = "✓ " if inst.get("id") == self._current().get("id") else "   "
            act = menu.addAction(f"{mark}{inst.get('name')}  :{inst.get('port')}")
            act.triggered.connect(lambda _c=False, i=inst: self._switch_instance(i["id"]))
        chosen = menu.exec(self.inst_more.mapToGlobal(self.inst_more.rect().bottomLeft()))
        if chosen is a_new:
            self._add_instance()
        elif chosen is a_rename:
            self._rename_instance()
        elif chosen is a_del:
            self._delete_instance()

    def _add_instance(self) -> None:
        dlg = NewInstanceDialog([int(i.get("port") or 0) for i in self._instances()], self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        new_id = _new_id("i")
        self._instances().append({
            "id": new_id, "name": dlg.result_item["name"], "port": dlg.result_item["port"],
            "lan": False, "auto_start": False, "routes": [],
        })
        self._instance = new_id
        self.store.save()
        self._sync_instance_tabs()
        self.port_edit.setText(str(dlg.result_item["port"]))
        self.lan_switch.setChecked(False)
        self.qr_btn.setVisible(False)
        self._sync_local(rebuild=True)
        self.local_hint.setText(i18n.tr("新实例已创建，点「启动服务」就能各自跑一个端口。"))

    def _rename_instance(self) -> None:
        inst = self._current()
        dlg = TextPromptDialog(i18n.tr("重命名实例"), i18n.tr("实例名称"),
                               str(inst.get("name") or ""), parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        inst["name"] = dlg.value()
        self.store.save()
        self._sync_instance_tabs()

    def _delete_instance(self) -> None:
        insts = self._instances()
        if len(insts) <= 1:
            self.local_hint.setText(i18n.tr("至少保留一个实例。"))
            return
        inst = self._current()
        self._srv().stop()
        insts[:] = [i for i in insts if i.get("id") != inst.get("id")]
        self._instance = insts[0].get("id") or "main"
        self.store.save()
        self._sync_instance_tabs()
        self.port_edit.setText(str(self._current().get("port") or DEFAULT_PORT))
        self.lan_switch.setChecked(bool(self._current().get("lan")))
        self._sync_local(rebuild=True)
        self.stateChanged.emit()

    # -------------------------------------------------- 启停
    def _toggle(self) -> None:
        if self._srv().running:
            self._stop()
        else:
            self._start()

    def _start(self) -> bool:
        inst, srv = self._current(), self._srv()
        try:
            port = int(self.port_edit.text() or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        from .mock_server import apply_scenario

        active = str(inst.get("active_scenario") or "")
        routes = apply_scenario(inst.get("routes") or [], self._cfg(), inst)
        for item in routes:
            item["_scenario"] = active or ""
        ok, msg = srv.start(routes, port,
                            bool(self._cfg().get("fallback_echo")),
                            bool(inst.get("lan")), scenario=active)
        if ok:
            inst["port"] = srv.port
            self.store.save()
            self.port_edit.setText(str(srv.port))
            tip = (i18n.tr("服务已启动，局域网也开着：手机扫码或直接访问上面的局域网地址。"
                           "改路由会立刻生效，不用重启。") if srv.lan else
                   i18n.tr("服务已启动：改路由会立刻生效，不用重启。"
                           "想把手机接进来，打开上面的「局域网」开关。"))
            # 端口被占用时 start() 会给一句「端口 8787 已被…，改用 8788」，别把它吞掉
            if ("端口" in msg or "重复" in msg) and "已启动" not in msg:
                tip = msg + "\n" + tip
            self.local_hint.setText(tip)
        else:
            self.local_hint.setText(msg)
        self._sync_local(rebuild=True)
        self.stateChanged.emit()
        return ok

    def _stop(self) -> None:
        srv = self._srv()
        port = srv.port
        srv.stop()
        if port and srv.port_in_use(port):
            self.local_hint.setText(
                i18n.trf("已停止，但端口 {port} 仍被其它程序占用（可能是另一个 Ocelot 实例）。",
                         port=port))
        else:
            self.local_hint.setText(i18n.tr("服务已停止。路由都保留着，重启后继续用。"))
        self._sync_local(rebuild=True)
        self.stateChanged.emit()

    def _on_lan(self, on: bool) -> None:
        inst = self._current()
        inst["lan"] = bool(on)
        self.store.save()
        self.qr_btn.setVisible(bool(on))
        if self._srv().running:
            self._start()
        else:
            self.local_hint.setText(
                i18n.tr("已开启局域网访问：启动后手机用本机 IP 就能连，点右边的扫码按钮出二维码。")
                if on else i18n.tr("只监听本机 127.0.0.1。"))
        self._sync_local()

    def _sync_local(self, rebuild: bool = False) -> None:
        t = theme()
        srv, inst = self._srv(), self._current()
        if hasattr(self, "scenario_btn"):
            self._sync_scenario_label()
        running = srv.running
        self.status_pill.set_text(i18n.tr("运行中") if running else i18n.tr("未启动"))
        self.status_pill.set_color(t.success if running else t.text_faint)
        self.start_btn.setText(i18n.tr("停止服务") if running else i18n.tr("启动服务"))
        self.start_btn.set_icon("stop" if running else "play")
        # 服务在跑时的「停止服务」也是断开语义，跟着变红
        self.start_btn.set_kind("danger" if running else "primary")
        self.qr_btn.setEnabled(running)
        shown = srv.base if running else f"http://127.0.0.1:{inst.get('port') or DEFAULT_PORT}"
        nets = srv.lan_urls() if running else []
        if nets:
            shown += "    ·    " + i18n.trf("局域网 {url}", url=nets[0])
        self.base_label.setText(shown)
        self.port_edit.setEnabled(not running)
        self.lan_switch.setEnabled(not running)
        if running:
            if not self.local_hint.text() or "已停止" in self.local_hint.text():
                self.local_hint.setText(i18n.trf(
                    "服务运行中：{url} —— 本机浏览器、脚本、手机都能连。", url=srv.base))
        else:
            if not self.local_hint.text() or "运行中" in self.local_hint.text():
                self.local_hint.setText(i18n.tr(
                    "启动后：请求发到 http://127.0.0.1:<端口>/<路径>；"
                    "打开「局域网」还能让手机直接连。"))
            self._check_port_owner()
        for row in self.route_rows:
            row.setup_buttons(running)
        if rebuild:
            self._rebuild_tree()
        self._sync_instance_tabs()

    def _self_check(self) -> None:
        """自检：真连一下自己。端口在、但服务被系统掐掉时能立刻发现。"""
        srv = self._srv()
        if not srv.running:
            return
        if srv.probe():
            return
        self.status_pill.set_text(i18n.tr("无响应"))
        self.status_pill.set_color(theme().danger)
        self.local_hint.setText(i18n.trf(
            "端口 {port} 还在监听，但服务没有响应：可能被系统回收了。"
            "点「停止服务」再「启动服务」即可恢复。", port=srv.port))

    def _check_port_owner(self) -> None:
        try:
            port = int(self.port_edit.text() or DEFAULT_PORT)
        except ValueError:
            return
        if not self._srv().port_in_use(port):
            return
        if MockServer._probe_ocelot(port):
            self.local_hint.setText(
                i18n.trf("端口 {port} 上已经有一个 Ocelot Mock 服务在响（可能是别的实例，"
                         "或上次没正常退出）。点「启动服务」会自动换端口。", port=port))
        else:
            self.local_hint.setText(
                i18n.trf("端口 {port} 已被其它程序占用。点「启动服务」会自动挑空闲端口。",
                         port=port))

    # -------------------------------------------------- 树
    def refresh_i18n(self) -> None:
        """语言切换后重建路由树：分组标题是自绘文本，得重新走一遍 tr。"""
        if hasattr(self, "routes_box"):
            self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        while self.routes_box.count() > 1:
            item = self.routes_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.route_rows.clear()
        routes = self._routes()
        hits = getattr(self._srv(), "hits", {}) or {}
        running = self._srv().running

        # 组装分组树：prefix -> 直接子分组 / 直接挂的路由
        children: Dict[str, List[str]] = {"": []}
        own: Dict[str, List[Dict[str, Any]]] = {"": []}
        for r in routes:
            g = str(r.get("group") or "").strip().strip("/")
            own.setdefault(g, []).append(r)
            if g:
                parts = g.split("/")
                for i in range(1, len(parts) + 1):
                    pre = "/".join(parts[:i])
                    parent = "/".join(parts[:i - 1])
                    children.setdefault(pre, [])
                    children.setdefault(parent, [])
                    if pre not in children[parent]:
                        children[parent].append(pre)

        def count_under(prefix: str) -> int:
            return sum(len(own.get(g, [])) for g in own
                       if g == prefix or g.startswith(prefix + "/"))

        def render(prefix: str, depth: int) -> None:
            for child in children.get(prefix, []):
                collapsed = child in self._collapsed
                row = GroupRow(child, i18n.tr(child.split("/")[-1]), count_under(child),
                               depth, collapsed)
                row.toggled.connect(self._toggle_group)
                row.menuRequested.connect(self._group_menu)
                self.routes_box.insertWidget(self.routes_box.count() - 1, row)
                if collapsed:
                    continue
                render(child, depth + 1)
            for r in own.get(prefix, []):
                row = RouteRow(r, running, hits=int(hits.get(r.get("name") or "", 0)),
                               indent=depth)
                row.edit.connect(self._edit_route)
                row.remove.connect(self._remove_route)
                row.copy.connect(self._copy_route)
                row.trial.connect(self._trial_route)
                self.route_rows.append(row)
                self.routes_box.insertWidget(self.routes_box.count() - 1, row)

        render("", 0)
        self.empty_label.setVisible(not routes)
        # 不要隐藏 scroll：它带 stretch=1，一旦 hide，剩余高度就会被上面几行
        # 均分（每行撑到 89px），行距突然变松 —— 新建实例切过去时就很明显。
        # 空路由时让它留着当空白填充，只藏空状态提示本身。
        groups = len({str(r.get("group") or "") for r in routes if r.get("group")})
        if self.tabs.current() == "local":
            self.hint.setText(
                i18n.trf("{n} 条路由 · {g} 个分组", n=len(routes), g=groups) if groups
                else i18n.trf("{n} 条路由", n=len(routes)))

    def _toggle_group(self, prefix: str) -> None:
        if prefix in self._collapsed:
            self._collapsed.discard(prefix)
        else:
            self._collapsed.add(prefix)
        self._rebuild_tree()

    def _group_menu(self, prefix: str, pos) -> None:
        t = theme()
        menu = Menu(self)
        a_new = menu.addAction(icons.icon("plus", t.text, 14), i18n.tr("在这个分组里新建路由…"))
        a_rename = menu.addAction(icons.icon("pencil", t.text, 14), i18n.tr("重命名分组…"))
        a_del = menu.addAction(icons.icon("trash", t.text, 14), i18n.tr("删除分组"))
        chosen = menu.exec(pos)
        if chosen is a_new:
            self._add_route(group=prefix)
        elif chosen is a_rename:
            dlg = TextPromptDialog(i18n.tr("重命名分组"), i18n.tr("分组名（用 / 分层）"),
                                   prefix, parent=self)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            new = dlg.value().strip("/")
            for r in self._routes():
                g = str(r.get("group") or "")
                if g == prefix or g.startswith(prefix + "/"):
                    r["group"] = new + g[len(prefix):]
            self.store.save()
            self._rebuild_tree()
        elif chosen is a_del:
            left = [r for r in self._routes()
                    if str(r.get("group") or "") == prefix
                    or str(r.get("group") or "").startswith(prefix + "/")]
            if left:
                self.local_hint.setText(
                    i18n.trf("分组「{g}」里还有 {n} 条路由，先把它们删掉再删分组。",
                             g=prefix, n=len(left)))
                return
            self._collapsed.discard(prefix)
            self._rebuild_tree()

    # -------------------------------------------------- 路由增删改
    def _add_route(self, group: Optional[str] = None) -> None:
        dlg = RouteDialog(self.store, None, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        item = dlg.result_item
        item["group"] = group or ""
        self._routes().append(item)
        self.store.save()
        self._rebuild_tree()
        self._restart_if_running()

    def _new_group(self) -> None:
        dlg = TextPromptDialog(i18n.tr("新建分组"), i18n.tr("分组名（用 / 分层）"),
                               "", i18n.tr("例如：订单/支付，导入时也会自动按文件夹分组"),
                               parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self._add_route(group=dlg.value().strip("/"))

    def _edit_route(self, item: Dict[str, Any]) -> None:
        dlg = RouteDialog(self.store, item, self)
        dlg.set_editing(item)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        for i, r in enumerate(self._routes()):
            if r.get("id") == item.get("id"):
                dlg.result_item["group"] = r.get("group") or ""
                self._routes()[i] = dlg.result_item
                break
        self.store.save()
        self._rebuild_tree()
        self._restart_if_running()

    def _remove_route(self, item: Dict[str, Any]) -> None:
        inst = self._current()
        inst["routes"] = [r for r in self._routes() if r.get("id") != item.get("id")]
        self.store.save()
        self._rebuild_tree()
        self._restart_if_running()

    def _copy_route(self, item: Dict[str, Any]) -> None:
        from PyQt6.QtGui import QGuiApplication

        srv = self._srv()
        if not srv.running:
            self.local_hint.setText(i18n.tr("先启动服务，才有地址可复制"))
            return
        lan = bool(self._current().get("lan"))
        QGuiApplication.clipboard().setText(srv.url_for(item.get("path") or "/", lan=lan))
        self.local_hint.setText(i18n.trf("已复制 {path}", path=item.get("path")))

    def _trial_route(self, item: Dict[str, Any]) -> None:
        srv = self._srv()
        if not srv.running:
            self.local_hint.setText(i18n.tr("先启动服务，再试用这条路由"))
            return
        self.trialRequested.emit((item.get("method") or "GET").upper(),
                                 srv.url_for(item.get("path") or "/"))
        # 这是独立窗口：试用完别自己关掉，主窗口里发请求时还能对照路由

    def _copy_base(self) -> None:
        from PyQt6.QtGui import QGuiApplication

        srv = self._srv()
        QGuiApplication.clipboard().setText(srv.base if srv.running else self.base_label.text())
        self.local_hint.setText(i18n.tr("根地址已复制"))

    def _on_fallback(self, on: bool) -> None:
        self._cfg()["fallback_echo"] = bool(on)
        self.store.save()
        self._restart_if_running()

    def _on_scenario(self) -> None:
        cfg, inst = self._cfg(), self._current()
        dlg = ScenarioDialog(cfg.get("scenarios") or [],
                             str(inst.get("active_scenario") or ""), self)
        if dlg.exec() != dlg.DialogCode.Accepted or not dlg.result_item:
            return
        item = dlg.result_item
        scenarios = {s.get("id"): s for s in cfg.get("scenarios") or []
                     if isinstance(s, dict)}
        scenarios[item["id"]] = item
        cfg["scenarios"] = list(scenarios.values())
        inst["active_scenario"] = item["id"]
        self.store.save()
        self._sync_scenario_label()
        self._restart_if_running()

    def _sync_scenario_label(self) -> None:
        active = str(self._current().get("active_scenario") or "")
        scenario = next((s for s in self._cfg().get("scenarios") or []
                         if isinstance(s, dict) and s.get("id") == active), None)
        name = (scenario or {}).get("name") or i18n.tr("正常")
        self.scenario_btn.setText(i18n.trf("场景：{name}", name=name))

    def _restart_if_running(self) -> None:
        if self._srv().running:
            self._start()
            self._sync_local(rebuild=True)

    def _show_qr(self) -> None:
        LanQrDialog(self._srv(), self).exec()

    # -------------------------------------------------- 导入 / AI
    def _import_doc(self) -> None:
        path, _flt = QFileDialog.getOpenFileName(
            self, i18n.tr("导入 OpenAPI / Postman"), "",
            "JSON (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
            routes, kind = mock_import.routes_from_document(text)
        except (OSError, ValueError) as exc:
            self.local_hint.setText(i18n.trf("导入失败：{err}", err=exc))
            return
        added = 0
        for r in routes:
            r["id"] = _new_id("m")
            r["group"] = r.get("group") or i18n.tr("导入")
            self._routes().append(r)
            added += 1
        self.store.save()
        self._rebuild_tree()
        self._restart_if_running()
        groups = len({r.get("group") for r in routes})
        self.local_hint.setText(
            i18n.trf("已从 {kind} 导入 {n} 条路由，按 {g} 个分组放好。", kind=kind,
                     n=added, g=groups))

    def _ai_generate(self) -> None:
        """一个入口两种产出：生成接口就直接插进来，生成用例就弹 cURL 清单。"""
        dlg = MockAiDialog(self._routes(), self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        if dlg.result_cases:
            CasesDialog(dlg.result_cases, self._srv().base, self).exec()
        if not dlg.result_routes:
            return
        for r in dlg.result_routes:
            r["id"] = _new_id("m")
            self._routes().append(r)
        self.store.save()
        self._rebuild_tree()
        self._restart_if_running()
        self.local_hint.setText(i18n.trf("AI 生成了 {n} 条路由，已经可以直接请求。",
                                         n=len(dlg.result_routes)))

    # -------------------------------------------------- 公开接口页
    def _page_public(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("Field")
        i18n.placeholder(self.search, "搜索接口、域名或用途，例如 登录 / json / 图片")
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
            self._sync_local(rebuild=True)
            self._self_check()
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
        self.hint.setText(i18n.trf("{n} 个公开接口 · 点一行新建请求", n=len(items)))

    def _pick(self, item: Dict[str, Any]) -> None:
        self.chosen.emit(item)

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
                    "包括方法、路径、状态码、耗时、体积与来源 IP。"),
            11.2, t.text_faint)
        self.logs_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logs_empty.setWordWrap(True)
        cl.addWidget(self.logs_empty)
        lay.addWidget(card, 1)
        return page

    def _clear_logs(self) -> None:
        self.hub.clear_logs()
        self._refresh_logs(force=True)

    def _refresh_logs(self, force: bool = False) -> None:
        entries = list(self.hub.logs)
        top = entries[:150]
        keys = [id(e) for e in top]
        if not force and keys == self._log_keys:
            return
        old = self._log_keys
        self._log_keys = keys

        # 新日志永远插在最前面：只要上一批还能在列表里对上，就只补新增的几条。
        # 以前每来一条日志就把 150 行全删了重造，请求一密集就明显卡顿。
        added = -1
        if old and keys:
            try:
                added = keys.index(old[0])
            except ValueError:
                added = -1
        if force or added < 0:
            self._rebuild_log_rows(top)
        elif added:
            for entry in reversed(top[:added]):
                row = LogRow(entry)
                self.log_rows.insert(0, row)
                self.logs_box.insertWidget(0, row)
            while len(self.log_rows) > 150:
                row = self.log_rows.pop()
                self.logs_box.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
        else:
            return

        self.logs_empty.setVisible(not entries)
        self.log_scroll.setVisible(bool(entries))
        self.log_stats.setText(self._log_summary(entries))
        if self.tabs.current() == "logs":
            self.hint.setText(i18n.trf("{n} 条请求", n=len(entries)) if entries
                              else i18n.tr("请求日志"))

    def _rebuild_log_rows(self, top: List[Dict[str, Any]]) -> None:
        while self.logs_box.count() > 1:
            item = self.logs_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.log_rows.clear()
        for entry in top:
            row = LogRow(entry)
            self.log_rows.append(row)
            self.logs_box.insertWidget(self.logs_box.count() - 1, row)
        self._log_rows_len = len(top)

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
        self._sync_instance_tabs()
        self._sync_local(rebuild=True)
        self._self_check()
        self._refresh_logs(force=True)
        if self.tabs.current() == "logs":
            self.log_timer.start()

    def hideEvent(self, e):
        # 面板收起来就别再每秒刷日志了：日志行留到下次打开时按需重建
        self.log_timer.stop()
        self._rebuild_log_rows([])
        self._log_keys = []
        super().hideEvent(e)

    def closeEvent(self, e):
        self.log_timer.stop()
        chat = self._chat
        if chat is not None and chat.isRunning():
            try:
                chat.cancel()
            except Exception:      # noqa: BLE001
                pass
        # 服务故意不停：关掉面板后它还在后台跑，底部徽章仍然能点回来
        self.stateChanged.emit()
        super().closeEvent(e)
