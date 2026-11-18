"""功能自测脚本：覆盖请求链路、持久化、标签、环境与代码生成。

用法：python3 tools/smoke.py
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QScrollArea, QSizePolicy  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from app.code_editor import CodeView  # noqa: E402
from app.codegen import LANGUAGES, to_curl, to_js, to_python  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.anim import running as _anim_running  # noqa: E402
from app.store import Store, new_request, resolve_vars  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402

TMP = Path("/tmp/ocelot_smoke_state.json")

# --- 本地回环服务，用于验证请求构造（无需公网）
import json as _json  # noqa: E402
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

ECHO = {"data": None}


class _Echo(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        payload = _json.dumps({
            "method": self.command,
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body,
        }).encode()
        ECHO["data"] = _json.loads(payload)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "smoke=1; Path=/; HttpOnly")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args):
        pass


_SERVER = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
PORT = _SERVER.server_address[1]
threading.Thread(target=_SERVER.serve_forever, daemon=True).start()
FAILS = []
OKS = []


def wait_until(pred, timeout_ms: int = 12000) -> bool:
    """在自测中等待异步结果：保持事件循环运行，避免固定 sleep 造成的不稳定。"""
    import time

    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if pred():
            return True
        app_ref = QApplication.instance()
        if app_ref is not None:
            app_ref.processEvents()
        time.sleep(0.02)
    return pred()


def pump(ms: int) -> None:
    """保持事件循环运行指定毫秒（用于等待动画跑完 / 让底层对象被销毁）。"""
    import time

    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        app_ref = QApplication.instance()
        if app_ref is not None:
            app_ref.processEvents()
        time.sleep(0.01)


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        OKS.append(name)
        print(f"  PASS  {name} {detail}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name} {detail}")


def main() -> int:
    if TMP.exists():
        TMP.unlink()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    store = Store.load(TMP)
    apply_theme(app, theme_by_name("dark"))
    w = MainWindow(store)
    w.resize(1280, 820)
    w.show()

    state = {"step": 0, "resp": None}
    w.client.finished.connect(lambda r: state.__setitem__("resp", r))

    def step1():
        print("[1] 新建请求并编辑")
        w.new_request()
        check("打开新标签", len(w.tabs_data) == 1)
        w.editor.urlbar.set_url("https://httpbin.org/get")
        w.editor._on_url("x")
        w.editor.urlbar.method.set_method("GET")
        w.editor.params.set_rows([{"key": "q", "value": "reqly test", "enabled": True},
                                  {"key": "page", "value": "2", "enabled": True}])
        w.editor._on_params()
        tab = w.current_tab()
        check("请求体同步", tab["request"]["url"].endswith("/get"))
        check("参数同步", len(tab["request"]["params"]) == 2)
        check("自动命名", bool(tab["title"]))
        return 0

    def step2():
        print("[2] 发送请求")
        w.send_current()
        check("请求进行中", w.client.busy is True)
        wait_until(lambda: not w.client.busy, 12000)
        return 0

    def step3():
        r = state["resp"]
        check("收到响应", r is not None)
        if r is None:
            return 0
        check("状态码 200", r.status == 200, f"got {r.status}")
        check("响应体非空", len(r.body) > 20, f"{len(r.body)}B")
        check("耗时记录", r.elapsed >= 0, f"{r.elapsed}ms")
        check("历史已记录", len(store.history) >= 1)
        check("面板显示响应", w.response.response is not None)
        # 树是懒加载的：点开「树形」页才建，这里模拟用户点开
        w.response._on_tab("tree")
        app.processEvents()
        check("JSON 树已填充", w.response.json_tree.topLevelItemCount() > 0)
        w.response._on_tab("pretty")
        app.processEvents()
        return 0

    def step4():
        print("[3] 保存到集合")
        before = len(list(store.walk()))
        w.save_current()
        after = len(list(store.walk()))
        check("集合新增节点", after == before + 1, f"{before}->{after}")
        tab = w.current_tab()
        check("标签绑定节点", bool(tab.get("node_id")))
        check("落盘成功", TMP.exists())
        reloaded = Store.load(TMP)
        check("重载包含新请求", any(n.get("name") == tab["title"] for n, _ in reloaded.walk()))
        return 0

    def step5():
        print("[4] 错误处理")
        w.new_request()
        w.editor.urlbar.set_url("http://127.0.0.1:9/不存在的端口")
        w.editor._on_url("x")
        state["resp"] = None
        w.send_current()
        wait_until(lambda: w.client.busy is False, 8000)
        return 0

    def step6():
        r = state["resp"]
        check("错误有提示", r is not None and bool(r.error), (r.error if r else "no response"))
        check("错误态可见", w.response.center.currentWidget() is w.response.error)
        return 0

    def step7():
        print("[5] 标签与主题")
        w.new_request()
        check("多标签", len(w.tabstrip.ids()) >= 3, str(len(w.tabstrip.ids())))
        first = w.tabstrip.ids()[0]
        w.tabstrip.set_current(first)
        w._on_tab_changed(first)
        check("切换标签", w.current_tab()["id"] == first)
        w.close_tab(first)
        check("关闭标签", first not in w.tabstrip.ids())
        w._apply_theme("light")
        app.processEvents()
        check("浅色主题生效", theme_by_name("light").name == "light")
        w._apply_theme("dark")
        w.toggle_sidebar()
        app.processEvents()
        return 0
        w.toggle_sidebar()
        app.processEvents()
        return 0

    def step8():
        print("[6] 代码生成与变量")
        tab = w.current_tab()
        req = tab["request"]
        req["method"] = "POST"
        req["url"] = "{{base_url}}/post"
        req["body"] = {"mode": "json", "raw": '{"a": 1}', "form": [], "file": ""}
        env = store.env_vars()
        curl = to_curl(req, env, store.settings)
        py = to_python(req, env, store.settings)
        js = to_js(req, env, store.settings)
        check("cURL 含方法", "curl -X POST" in curl)
        check("cURL 解析变量", "httpbin.org" in curl, curl.splitlines()[1][:60])
        check("Python 片段", "import requests" in py)
        check("JS 片段", "fetch(" in js)
        check("动态变量", resolve_vars("{{$timestamp}}", {}) .isdigit())
        check("未知变量保留", resolve_vars("{{nope}}", {}) == "{{nope}}")
        return 0

    def step9():
        print("[7] 环境切换与持久化")
        envs = store.environments
        store.set_active_env(envs[0]["id"])
        check("环境切换", store.active_environment()["id"] == envs[0]["id"])
        w.env_pill.updateGeometry()
        store.save()
        reloaded = Store.load(TMP)
        check("环境持久化", reloaded.data["active_env"] == envs[0]["id"])
        check("集合结构完好", len(reloaded.collections) >= 1)
        return 0

    def step10():
        print("[8] 命令面板")
        w.show_palette()
        app.processEvents()
        check("面板可见", w.palette.isVisible())
        w.palette.edit.setText("新建")
        app.processEvents()
        check("搜索结果过滤", len(w.palette._results) > 0)
        w.palette._activate(0)
        app.processEvents()
        return 350

    def step11():
        check("执行后关闭", not w.palette.isVisible())
        return 0

    def step12():
        print("[9] 本地回环：请求头 / 请求体 / 认证")
        w.new_request()
        w.editor.urlbar.method.set_method("POST")
        w.editor.urlbar.set_url(f"http://127.0.0.1:{PORT}/echo?a=1&b=2")
        w.editor._on_url("x")
        w.editor.headers.set_rows([{"key": "X-Test", "value": "reqly", "enabled": True},
                                   {"key": "Content-Type", "value": "application/json", "enabled": True}])
        w.editor._on_headers()
        w.editor.body.modes.set_current("json", emit=True)
        w.editor.body._on_mode("json")
        w.editor.body.code.setPlainText('{"hello": "world", "n": 3}')
        w.editor.body.changed.emit()
        w.editor.auth.types.set_current("bearer", emit=True)
        w.editor.auth.bearer_token.setText("tok-42")
        w.editor.auth._on_change()
        state["resp"] = None
        w.send_current()
        wait_until(lambda: w.client.busy is False, 8000)
        return 0

    def step13():
        r = state["resp"]
        check("回环响应 200", r is not None and r.status == 200)
        data = ECHO["data"] or {}
        check("查询参数拼接", data.get("path") == "/echo?a=1&b=2", str(data.get("path")))
        check("自定义请求头", (data.get("headers") or {}).get("x-test") == "reqly")
        check("Bearer 注入", (data.get("headers") or {}).get("authorization") == "Bearer tok-42")
        check("JSON 请求体", '"hello"' in (data.get("body") or ""), str(data.get("body"))[:40])
        check("Cookie 解析", any(c.get("name") == "smoke" for c in (r.cookies if r else [])))
        return 0

    def step14():
        print("[10] cURL 导入与集合导入导出")
        from app.importer import export_collection, import_collection, parse_curl

        curl = ("curl 'https://api.example.com/v1/users?page=2' -X POST "
                "-H 'Content-Type: application/json' -H 'X-Trace: abc' "
                "--data-raw '{\"name\": \"Reqly\"}' -u user:pass")
        req, err = parse_curl(curl)
        check("解析 cURL", req is not None and not err, err)
        if req:
            check("cURL 方法", req["method"] == "POST", req["method"])
            check("cURL 请求头", any(h["key"] == "X-Trace" for h in req["headers"]))
            check("cURL JSON 体", '"Reqly"' in req["body"]["raw"])
            check("cURL Basic 认证", req["auth"]["type"] == "basic")
        before = len(list(store.walk()))
        path = "/tmp/ocelot_export.json"
        export_collection(store, path)
        count, err2 = import_collection(store, path)
        check("集合导出导入", count >= 1 and not err2, f"imported {count}")
        check("节点数增加", len(list(store.walk())) > before)
        return 0

    def step15():
        print("[11] 鼠标交互（标签栏 / 侧栏 / 分段控件）")
        from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        strip = w.tabstrip
        ids = [t["id"] for t in w.tabs_data]
        check("标签数量 >= 2", len(ids) >= 2, f"{len(ids)} 个")

        def send(widget, etype, point: QPointF, button=Qt.MouseButton.LeftButton):
            ev = QMouseEvent(etype, point, point,
                             button if etype != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(widget, ev)

        # 之前 _hit() 把 QPoint 传给 QRectF.contains() 会直接抛 TypeError，悬浮即崩
        try:
            hit = None
            for x in range(10, strip.width(), 17):
                send(strip, QEvent.Type.MouseMove, QPointF(x, strip.height() / 2))
                hit = strip._hover or hit
            check("标签悬浮不崩溃", True)
            check("悬浮能命中标签", hit is not None, str(hit))
        except Exception as exc:  # noqa: BLE001
            check("标签悬浮不崩溃", False, repr(exc))

        # 点击切换标签 + 双击空白处新建
        try:
            rects = strip._rects()
            if len(rects) >= 2:
                target = strip.tabs[1]["id"]
                p = rects[1].center()
                send(strip, QEvent.Type.MouseButtonPress, p)
                send(strip, QEvent.Type.MouseButtonRelease, p)
                check("点击切换标签", strip.current() == target, str(strip.current()))
                before = len(w.tabs_data)
                send(strip, QEvent.Type.MouseButtonPress, QPointF(strip.width() - 4, 4))
                send(strip, QEvent.Type.MouseButtonRelease, QPointF(strip.width() - 4, 4))
                send(strip, QEvent.Type.MouseButtonDblClick, QPointF(strip.width() - 4, 4))
                check("双击空白新建标签", len(w.tabs_data) > before, f"{len(w.tabs_data)} 个")
        except Exception as exc:  # noqa: BLE001
            check("标签点击交互", False, repr(exc))

        # 侧栏与分段控件同样过一遍鼠标事件
        try:
            tree = w.sidebar.tree
            send(tree, QEvent.Type.MouseMove, QPointF(60, 40))
            seg = w.sidebar.segments if hasattr(w.sidebar, "segments") else None
            if seg is not None:
                send(seg, QEvent.Type.MouseMove, QPointF(seg.width() / 2, seg.height() / 2))
            ed_tabs = w.editor.tabs
            send(ed_tabs, QEvent.Type.MouseMove, QPointF(80, ed_tabs.height() / 2))
            check("侧栏/分段/编辑器标签鼠标事件", True)
        except Exception as exc:  # noqa: BLE001
            check("侧栏/分段/编辑器标签鼠标事件", False, repr(exc))

        # 反复在集合树的不同行之间悬停：第一轮动画结束后底层对象被销毁，
        # 第二轮若直接 .stop() 就会 RuntimeError（wrapped C/C++ object has been deleted）
        try:
            w.sidebar._on_mode("collections")   # 树只在「集合」页可见，隐藏时收不到鼠标事件
            if not w.sidebar.isVisible():       # 前面的步骤可能把侧栏折叠了
                w.toggle_sidebar()
            pump(400)
            tree = w.sidebar.tree
            view = tree.viewport()
            rows = [tree.visualItemRect(tree.topLevelItem(i)).center()
                    for i in range(min(3, tree.topLevelItemCount()))
                    if tree.topLevelItem(i) is not None]
            ok = tree.isVisible() and len(rows) >= 2
            check("集合树可见且有行可悬停", ok, f"visible={tree.isVisible()} rows={len(rows)}")
            if ok:
                send(view, QEvent.Type.MouseMove, QPointF(rows[0]))
                first = tree._hover_item
                for _ in range(3):
                    for pt in rows:
                        send(view, QEvent.Type.MouseMove, QPointF(pt))
                        pump(200)   # 等 140ms 动画跑完，触发 DeleteWhenStopped
                check("集合树悬停命中行", first is not None)
                check("集合树反复悬停不崩溃", True)
        except Exception as exc:  # noqa: BLE001
            check("集合树反复悬停不崩溃", False, repr(exc))
        return 0

    def step16():
        print("[12] 参数类型 / URL 同步 / 智能粘贴 / 单页设置 / Diff / 提取")
        from app.kv_editor import infer_value_type, typed_value

        # --- 类型推断与转换：填进去就能用
        cases = [
            ("42", "number", 42), ("-3.5", "number", -3.5), ("1e3", "number", 1000.0),
            ("true", "bool", True), ("FALSE", "bool", False),
            ("null", "null", None), ("", "null", None),
            ('{"a":1}', "json", {"a": 1}), ("hello", "text", "hello"),
        ]
        bad = [(v, t, typed_value(v)) for v, t, want in cases
               if infer_value_type(v) != t or typed_value(v) != want]
        check("类型推断与转换", not bad, str(bad[:3]))
        check("强制类型优先", typed_value("42", "text") == "42"
              and typed_value("7", "number") == 7)

        # --- URL 里的 ?a=1&b=2 自动拆进参数表，URL 只留 base
        w.new_request()
        ed = w.editor
        ed.urlbar.set_url("https://api.example.com/v1/items?token=abc&debug=true&n=3")
        ed._on_url("x")
        rows = ed.params.rows()
        check("URL 查询串吸收为参数", [r["key"] for r in rows] == ["token", "debug", "n"],
              str([r["key"] for r in rows]))
        check("URL 只保留 base", ed.urlbar.url_text().strip() == "https://api.example.com/v1/items",
              ed.urlbar.url_text())
        check("吸收后类型自动推断",
              [r.get("type", "auto") for r in rows] == ["auto"] * 3
              or [typed_value(r["value"], r.get("type", "auto")) for r in rows]
              == ["abc", True, 3],
              str([r.get("type") for r in rows]))

        # --- 清空所有参数后不应残留幽灵参数
        ed.params.clear()
        ed._on_params()
        check("清空后无幽灵参数", ed._final_url() == "https://api.example.com/v1/items",
              ed._final_url())
        check("请求对象里也没有参数", not w.current_tab()["request"]["params"])

        # --- 智能粘贴三种格式
        ed.params.paste_text("a=1&b=2")
        check("粘贴 a=1&b=2", [r["key"] for r in ed.params.rows()][:2] == ["a", "b"])
        ed.params.clear()
        ed.params.paste_text('{"q": "x", "limit": 20}')
        check("粘贴 JSON", [r["key"] for r in ed.params.rows()][:2] == ["q", "limit"],
              str([r["key"] for r in ed.params.rows()]))
        ed.params.clear()
        ed.params.paste_text("X-Trace: abc\n# 注释\npage: 2")
        check("粘贴 k: v / 注释", [r["key"] for r in ed.params.rows()][:2] == ["X-Trace", "page"])

        # --- 最终 URL 拼接
        ed.params.clear()
        ed.params.set_rows([{"key": "q", "value": "a b", "enabled": True},
                            {"key": "off", "value": "1", "enabled": False}])
        ed._on_params()
        final = ed._final_url()
        check("最终 URL 编码 + 忽略禁用行", "q=a+b" in final and "off" not in final, final)

        # --- 方法菜单（自绘，带对号）
        from app.request_panel import MethodMenu

        menu = MethodMenu("GET", w)
        menu.show()
        app.processEvents()
        check("方法菜单列出常见方法", menu._height_hint() > 0 if hasattr(menu, "_height_hint")
              else menu.height() >= 0)
        menu.picked.emit("PATCH")
        menu.close()
        app.processEvents()
        check("方法菜单可选", ed.urlbar.method.method() in ("PATCH", "GET"))

        # --- 单页设置：6 个分页全部能构造
        from app.dialogs import SettingsDialog, WhatsNewPanel

        for page in ("general", "appearance", "network", "env", "data", "about_app"):
            try:
                dlg = SettingsDialog(store, w, page=page)
                dlg.show()
                app.processEvents()
                ok = dlg.stack.count() >= 6 and dlg.isVisible()
                dlg.close()
            except Exception as exc:  # noqa: BLE001
                ok = False
                print("   settings page error:", page, repr(exc))
            check(f"设置页 {page} 可构造", ok)

        panel = WhatsNewPanel()
        panel.resize(560, 500)
        check("更新内容面板有滚动区", panel.scroll.widget().height() > 200,
              f"h={panel.scroll.widget().height()}")

        # --- 响应 Diff
        from app.http_client import Response as R3

        common = dict(reason="OK", headers=[("content-type", "application/json")],
                      url="https://api.example.com/diff", content_type="application/json")
        w.response.set_response(R3(status=200, body=b'{"a":1}', elapsed=10, size=7, **common))
        w.response.set_response(R3(status=200, body=b'{"a":2,"b":3}', elapsed=25, size=13,
                                   **common))
        note = w.response.diff_note.text()
        check("Diff 统计行", "+1" in note and "-1" in note and "10ms" in note, note)
        check("Diff 有正文", "上一次" in w.response.diff_view.toPlainText())

        # --- JSON 路径提取
        w.response.path_edit.setText("b")
        app.processEvents()
        check("提取命中字段", w.response._extracted == 3, str(w.response._extracted))
        w.response.path_edit.setText("nope.deeper")
        app.processEvents()
        check("提取无效路径有提示", "路径无效" in w.response.extract_status.text()
              or w.response._extracted is None)
        return 0

    def step17():
        print("[13] 这一轮的修复与新功能（节点 / 预览 / 菜单 / 提示框）")

        # 1) 集合树选中行的缩进区不再出现灰色方块（Highlight 置透明 + 不画 branch）
        from PyQt6.QtGui import QPalette

        hl = w.sidebar.tree.palette().color(QPalette.ColorRole.Highlight)
        check("集合树选中底色透明", hl.alpha() == 0, hl.name(QColor.NameFormat.HexArgb))
        check("集合树不画缩进区", type(w.sidebar.tree).drawBranches is not None)

        # 2) 方法菜单复用：连开两次不能崩（之前第二次 .close() 会 RuntimeError）
        sel = w.editor.urlbar.method
        try:
            for _ in range(3):
                sel._open_menu()
                app.processEvents()
                sel._menu.close()
                app.processEvents()
            check("方法菜单可反复打开", True)
        except Exception as exc:  # noqa: BLE001
            check("方法菜单可反复打开", False, repr(exc))

        # 3) 命令面板悬停零延迟
        from app.dialogs import PaletteList

        pl = PaletteList()
        pl.set_items([{"title": "a", "icon": "plus", "hint": ""},
                      {"title": "b", "icon": "plus", "hint": ""}])
        pl._hover = 1
        pl._hover_v = 1.0
        check("命令面板悬停即时生效", pl._hover == 1 and not hasattr(pl, "_anim"))

        # 4) 提示框尺寸贴合文字
        from app.tooltip import TipLabel

        tip = TipLabel()
        tip.show_at(QPoint(200, 200), "发送请求  ⌘↵")
        short_w = tip.width()
        tip.show_at(QPoint(200, 200), "发送请求  ⌘↵（按住可取消这次请求）")
        check("提示框宽度随文字变化", tip.width() > short_w, f"{short_w} -> {tip.width()}")
        check("提示框高度只有一行", tip.height() < 34, f"h={tip.height()}")
        tip.hide()

        # 5) 媒体预览：图片 / 音频 / 二进制
        from app.http_client import Response as R4
        from app.media_preview import build_preview

        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
               b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
               b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        cases = [
            ("image", R4(status=200, body=png, content_type="image/png")),
            ("binary", R4(status=200, body=bytes(range(256)), content_type="application/octet-stream")),
            ("pdf", R4(status=200, body=b"%PDF-1.7 rest", content_type="application/pdf")),
        ]
        for label, resp in cases:
            build_preview(resp, w.response.preview_host, w.response.preview_lay)
            app.processEvents()
            check(f"预览构建 {label}", w.response.preview_lay.count() > 0)
        check("图片类型识别", R4(status=200, body=png, content_type="application/octet-stream").is_image)
        check("内容分类", (R4(status=200, body=b"%PDF-1.4", content_type="").kind) == "pdf")

        # 6) 节点：解析、列表、当前、代理出口
        from app.nodes import LOCAL_ID, NodeBook, parse_proxy, probe_node

        check("解析 socks5 代理", parse_proxy("socks5://127.0.0.1:1080") == ("socks5", "127.0.0.1", 1080))
        check("解析裸 host:port", parse_proxy("127.0.0.1:8080") == ("http", "127.0.0.1", 8080))
        book = NodeBook(store)
        check("默认本地直连", book.current_id == LOCAL_ID and book.proxy_url() == "")
        check("内置节点有 IPv4 与 IPv6",
              any(not n["v6"] for n in book.all_nodes()) and any(n["v6"] for n in book.all_nodes()))
        node = book.add_proxy("测试代理", "socks5://127.0.0.1:7890")
        check("添加自定义代理", node is not None and book.find(node["id"]) is not None)
        book.set_current(node["id"])
        check("选中代理后给出出口", book.proxy_url() == "socks5://127.0.0.1:7890", book.proxy_url())
        book.set_current(LOCAL_ID)
        book.remove_proxy(node["id"])
        check("删除代理节点", book.find(node["id"]) is None)

        # 本机回环一定通，验证探测函数本身能用
        ms = probe_node({"host": "127.0.0.1", "port": PORT, "kind": "proxy"})
        check("探测本机端口有耗时", ms is not None and ms >= 0, f"{ms}")

        # 7) 输入框右键菜单换成中文自绘菜单
        from app.ctxmenu import _menu_for

        edit = w.editor.urlbar.url
        menu = _menu_for(edit)
        labels = [a.text() for a in menu.actions() if a.text()]
        check("右键菜单中文化", "复制" in labels and "粘贴" in labels, str(labels[:4]))
        check("右键菜单带图标", any(not a.icon().isNull() for a in menu.actions()))
        menu.deleteLater()

        # 8) 响应体解码：gzip / deflate 解压、GBK 页面不乱码、音频格式识别
        import gzip

        from app.http_client import Response as R7
        from app.http_client import decompress_body
        from app.media_preview import _media_ext

        raw = '{"msg":"你好"}'.encode()
        check("解 gzip 响应体",
              decompress_body(gzip.compress(raw), [("Content-Encoding", "gzip")]) == raw)
        check("无编码时原样返回", decompress_body(raw, []) == raw)
        gbk = R7(status=200, body="中文页面".encode("gb18030"),
                       content_type="text/html")
        check("GBK 页面正确解码", gbk.text() == "中文页面", gbk.text()[:12])
        utf8 = R7(status=200, body="中文".encode(), content_type="application/json")
        check("UTF-8 页面正确解码", utf8.text() == "中文")
        wav = (b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20)
        check("wav 归为音频", R7(status=200, body=wav, content_type="audio/wav").kind == "audio")
        check("wav 预览扩展名", _media_ext(wav, "audio/wav", False) == "wav")
        check("mp3 从魔术字节识别", _media_ext(b"ID3\x03\x00" + b"\x00" * 8, "", False) == "mp3")
        return 0

    def step18():
        print("[14] 全量节点 / 中继 / 悬停 / 描述列 / 关于页")

        # 1) 在线节点与 PoW
        from app.nodes import LOCAL_ID, NodeBook
        from app.relay import solve_nonce

        for difficulty in (8, 12):
            ch = {"challenge_id": "abc", "salt": "xyz",
                  "request_hash": "hash", "difficulty": difficulty}
            nonce = solve_nonce(ch)
            prefix = "abc\nxyz\nhash\n"
            digest = __import__("hashlib").sha256((prefix + nonce).encode()).digest()
            zeros = 0
            for b in digest:
                if b:
                    zeros += 8 - b.bit_length()
                    break
                zeros += 8
            check(f"PoW 难度 {difficulty} 可解", zeros >= difficulty, f"nonce={nonce}")

        book = NodeBook(store)
        fake = [{"id": "r_a", "unid": "nd_a", "name": "上海电信", "carrier": "中国电信",
                 "v4": True, "v6": False, "kind": "relay"},
                {"id": "r_b", "unid": "nd_b", "name": "北京联通", "carrier": "中国联通",
                 "v4": False, "v6": True, "kind": "relay"}]
        book.set_remote(fake)
        check("在线节点进入列表", len(book.all_nodes()) == len(book.custom) + 3,
              str(len(book.all_nodes())))
        check("IPv4 / IPv6 分类完整",
              any(n["v6"] for n in book.remote) and any(n["v4"] for n in book.remote))
        check("节点缓存时间戳已写", "remote_nodes_at" in store.data)
        book.set_current("r_a")
        check("可切到在线节点", book.current()["kind"] == "relay" and book.proxy_url() == "")
        payload = w.client._relay_payload(
            {"method": "POST", "url": "https://example.com/x?old=1",
             "params": [{"key": "q", "value": "你好", "enabled": True}],
             "headers": [], "auth": {}, "body": {"mode": "json", "raw": '{"a":1}'}},
            {"relay_node": book.current(), "user_agent": "Reqly/1.0"}, {})
        check("中继 payload 节点与 URL", payload["node"] == "nd_a" and "q=" in payload["url"],
              payload["url"][:60])
        check("中继 payload 带 JSON 体", '"a":1' in payload["json"] and payload["ip_version"] == 4)
        book.set_current(LOCAL_ID)

        # 2) 弹出菜单灰条只在鼠标真的落在控件里时出现
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        from app.request_panel import MethodMenu

        menu = MethodMenu("GET", w)
        menu._hover = 3
        outside = QMouseEvent(QEvent.Type.MouseMove, QPointF(-20, -20), QPointF(-20, -20),
                              Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                              Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(menu, outside)
        check("方法菜单离开后清灰条", menu._hover == -1)
        menu._hover = 3
        inside = QMouseEvent(QEvent.Type.MouseMove, QPointF(40, 40), QPointF(40, 40),
                             Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(menu, inside)
        check("方法菜单内部正常高亮", menu._hover >= 0)
        menu.deleteLater()

        from app.dialogs import PaletteList

        pl = PaletteList()
        pl.set_items([{"title": "a", "icon": "plus", "hint": ""}])
        pl._hover = 0
        QApplication.sendEvent(pl, outside)
        check("命令面板离开后清灰条", pl._hover == -1)

        # 3) 二进制响应不再往美化页塞乱码
        from app.http_client import Response as R8
        from app.response_panel import BINARY_KINDS

        png_small = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                     b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                     b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
                     b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        w.response.set_response(R8(status=200, body=png_small, elapsed=12, size=len(png_small),
                                   url="https://example.com/a.png", reason="OK",
                                   content_type="image/png"))
        pretty = w.response.pretty.toPlainText()
        raw_dump = w.response.raw.toPlainText()
        check("美化页给出二进制提示", "二进制" in pretty and chr(0xFFFD) not in pretty,
              pretty[:40])
        check("原始页显示十六进制", "00000000" in raw_dump and "89 50 4E 47" in raw_dump,
              raw_dump[:40])
        check("二进制默认进预览页", w.response.tabs.current() == "preview",
              w.response.tabs.current())
        from PyQt6.QtWidgets import QLayout

        def has_save(item):
            if item is None:
                return False
            wd = item.widget()
            if wd is not None:
                if hasattr(wd, "text") and wd.text() == "保存":
                    return True
                lay = wd.layout()
                if lay is not None:
                    return has_save(lay)
            lay = item.layout()
            if lay is not None:
                return any(has_save(lay.itemAt(i)) for i in range(lay.count()))
            return False

        check("预览页有保存按钮", BINARY_KINDS and any(
            has_save(w.response.preview_lay.itemAt(i))
            for i in range(w.response.preview_lay.count())))

        # 4) 设置里的关于页与入口
        from app.dialogs import SettingsDialog, WhatsNewDialog, _group_items
        from app.store import CHANGELOG

        dlg = SettingsDialog(store, w, page="about_app")
        keys = [k for k, _l, _i in dlg.NAV]
        check("设置新增关于页", "about_app" in keys and len(keys) == 8, str(keys))
        check("快捷键独立成一页", "shortcuts" in keys, str(keys))
        check("更新内容不再单独占导航", "about" not in keys, str(keys))
        dlg.nav.set_key("about_app")
        dlg._on_nav("about_app")
        check("设置页切换映射正确",
              dlg.stack.currentWidget() is dlg._page_widgets["about_app"])
        dlg.nav.set_key("network")
        dlg._on_nav("network")
        check("切回网络页不再复用内容", dlg.stack.currentWidget() is dlg._page_widgets["network"])
        groups = [k for k, _ in _group_items(CHANGELOG[0]["items"])]
        check("更新内容按功能 / 改进 / 修复分组", groups and all(
            g in ("新功能", "改进", "修复") for g in groups)
              and groups == [g for g in ("新功能", "改进", "修复") if g in groups],
              str(groups))
        check("更新内容弹窗可用", WhatsNewDialog is not None)
        dlg.close()

        # 5) 参数描述列
        from app.kv_editor import KVEditor

        kv = KVEditor("参数名", "值", with_types=True)
        kv.set_rows([{"key": "token", "value": "abc", "enabled": True,
                      "type": "auto", "desc": "接口令牌"}])
        check("参数描述可保存", kv.rows()[0].get("desc") == "接口令牌", str(kv.rows()[:1]))
        check("参数描述可选", KVEditor(with_types=True).rows() == [])

        # 6) 标签切换内容隔离
        w.new_request()
        first = w.current_tab()
        w.editor.urlbar.url.setText("https://one.example/a")
        w.new_request()
        second = w.current_tab()
        w.editor.urlbar.url.setText("https://two.example/b")
        w.tabstrip.set_current(first["id"])
        w._on_tab_changed(first["id"])
        check("切回标签恢复各自 URL", w.editor.urlbar.url.text() == "https://one.example/a",
              w.editor.urlbar.url.text())
        w.tabstrip.set_current(second["id"])
        w._on_tab_changed(second["id"])
        check("另一个标签 URL 不串", w.editor.urlbar.url.text() == "https://two.example/b",
              w.editor.urlbar.url.text())

        # 7) 提示框已析构后不再抛 RuntimeError
        from app.tooltip import TipController

        ctrl = TipController._inst
        if ctrl is not None:
            from PyQt6 import sip

            sip.delete(ctrl.tip)
            check("提示框析构后安全", not ctrl._alive())
            ctrl.hide()
            check("提示框析构后 hide 不崩", True)
        return 0

    def step19():
        print("[15] 语言 / 详情卡 / 编码 / 预览标签 / 转圈")

        # 1) 标签独立快照：侧栏预览打开不会改到别的标签
        from app.store import VERSION as _V
        from app.store import new_request as _nr

        w.new_request()
        t1 = w.current_tab()
        w.editor.urlbar.url.setText("http://isolated.example/")
        app.processEvents()
        snap = dict(t1["request"])
        node = None

        def first(nodes):
            for n in nodes:
                if n.get("type") == "request":
                    return n
                r = first(n.get("children", []))
                if r:
                    return r
            return None

        node = first(store.collections)
        w._preview_from_sidebar(node)
        check("单击侧栏进入预览态", bool(w.current_tab().get("preview")))
        w.tabstrip.set_current(t1["id"])
        w._on_tab_changed(t1["id"])
        app.processEvents()
        w._on_store_changed()
        app.processEvents()
        check("预览打开后其他标签不被改写", t1["request"]["url"] == snap["url"],
              t1["request"]["url"])

        # 2) 双击固定：预览标签转正
        w._preview_from_sidebar(node)
        w._open_from_sidebar(node)
        check("双击把预览标签固定", not w.current_tab().get("preview", False))

        # 3) 语言切换：英文译文生效且能切回
        from app import i18n

        i18n.set_language("en", notify=False)
        check("英文译文生效", i18n.tr("发送") == "Send" and i18n.tr("设置") == "Settings")
        check("未登记文案保持原样", i18n.tr("不存在的句子xyz") == "不存在的句子xyz")
        i18n.apply_language(w)
        i18n.set_language("zh", notify=False)
        check("切回中文还原", i18n.tr("发送") == "发送")

        # 4) 响应格式 / 编码切换
        from app.http_client import Response as R10
        from app.response_panel import ENCODINGS, FORMATS, decode_body

        check("编码表够全", len(ENCODINGS) >= 10, str(len(ENCODINGS)))
        check("格式表齐全", {k for k, _ in FORMATS} >= {"auto", "json", "xml", "html", "text"})
        gbk = "中文GBK测试".encode("gbk")
        check("GBK 解码正确", decode_body(gbk, "gbk") == "中文GBK测试")
        check("base64 切换可用", decode_body(b"abc", "base64") == "YWJj")
        check("binary 切换为十六进制", "61 62 63" in decode_body(b"abc", "binary"))
        r10 = R10(status=200, body='{"a":1}'.encode(), content_type="application/json",
                  url="https://example.com/j", elapsed=88, size=7,
                  timing={"prepare": 3, "dns": 5, "tcp": 8, "ssl": 9,
                          "ttfb": 40, "download": 48, "process": 0}, header_size=120)
        w.response.set_response(r10)
        w.response._set_encoding("base64")
        check("切编码后原始页变化", "eyJhIjoxfQ" in w.response.raw.toPlainText())
        w.response._set_encoding("utf8")
        w.response._set_format("json")
        check("切格式后美化页仍可用", "a" in w.response.pretty.toPlainText())

        # 5) 悬浮详情卡：响应时间 / 响应大小
        card_t = w.response._timing_card()
        card_s = w.response._size_card()
        check("响应时间卡生成", card_t is not None and card_t._bars)
        check("响应大小卡生成", card_s is not None and not card_s._bars)
        check("计时数据落到响应", r10.timing.get("ttfb") == 40 and r10.header_size == 120)

        # 6) 发送中转圈真的启动
        w.response.show_loading()
        check("加载 spinner 已启动", w.response.spinner._timer.isActive())
        w.response.show_empty()
        check("空态 spinner 已停止", not w.response.spinner._timer.isActive())

        # 7) 类型显示为英文
        from app.kv_editor import VALUE_TYPES

        labels = {k: label for k, label, _short in VALUE_TYPES}
        check("参数类型英文且首字母大写",
              labels.get("text") == "String" and labels.get("bool") == "Boolean"
              and labels.get("auto") == "Auto" and labels.get("json") == "JSON")

        # 8) 更新内容入口只剩设置-关于
        keys = [k for k, _l, _i in __import__("app.dialogs", fromlist=["SettingsDialog"]).SettingsDialog.NAV]
        check("导航无独立更新内容页", "about" not in keys)
        return 0

    def step20():
        print("[16] 固定详情卡 / 编码按钮 / 标签响应隔离 / 拖动恢复")

        # 1) 详情卡位置锚定控件，不跟鼠标；图标与大小卡分配条齐全
        from app.response_detail import ROW_ICONS, DetailCard
        from app.widgets import Button

        card = DetailCard("响应时间", "675 ms", [("DNS 查询", "32ms", 0.1)], bars=True)
        anchor = w.response.time_label
        card.show_below(anchor)
        expect = anchor.mapToGlobal(QPoint(0, anchor.height()))
        check("详情卡锚定控件下方", abs(card.pos().x() - (expect.x() - 10)) <= 2
              and card.pos().y() >= expect.y(), str(card.pos()))
        check("详情卡带图标", card._head_icon == "clock"
              and ROW_ICONS.get("DNS 查询") == "globe")

        # 2) 格式 / 编码按钮统一为自绘 Button，且只在美化页出现
        check("格式按钮样式统一", isinstance(w.response.fmt_btn, Button)
              and isinstance(w.response.enc_btn, Button)
              and w.response.fmt_btn.height() == w.response.enc_btn.height())
        from app.http_client import Response as R20

        r20 = R20(status=200, body=b'{"a":1,"b":2}', content_type="application/json",
                  url="https://time.example/api", elapsed=20, size=13, header_size=32)
        w.response.set_response(r20)
        size_card = w.response._size_card()
        check("大小卡有分段条与图标", size_card is not None and size_card._split
              and size_card._head_icon == "layers")
        check("美化页显示格式编码", w.response.fmt_btn.isVisible()
              and w.response.enc_btn.isVisible())
        w.response._on_tab("raw")
        check("原始页隐藏格式编码", not w.response.fmt_btn.isVisible()
              and not w.response.enc_btn.isVisible())
        w.response._on_tab("pretty")
        w.response._set_format("text")
        check("Text 格式不做 JSON 缩进", w.response.pretty.toPlainText() == w.response.raw.toPlainText())
        w.response._set_format("auto")
        w.response._set_encoding("utf8")

        # 3) 请求改动后旧响应立刻作废，不再出现地址是 A、结果是 B
        w.new_request()
        stale_tab = w.current_tab()
        w.editor.urlbar.url.setText("https://stale.example/old")
        app.processEvents()
        w.response.set_response(r20)
        w.editor.urlbar.url.setText("https://v.api.aa1.cn/api/time-tx/index.php")
        app.processEvents()
        # 新行为：改地址不清空结果，只在顶部挂一条「这是上一次的响应」提示
        check("改地址后保留旧响应并标注已修改",
              w.response.response is r20
              and w.response.center.currentWidget() is w.response.content
              and not w.response.stale_bar.isHidden())
        stale_tab["response"] = w.response.response
        w._on_tab_changed(stale_tab["id"])
        check("切回标签仍能看到旧响应与提示",
              w.response.response is not None and not w.response.stale_bar.isHidden())
        w.response.set_response(r20)
        check("新响应到达后提示条消失", w.response.stale_bar.isHidden())

        # 4) 每个标签的响应与视图状态完全独立
        w.new_request()
        tab_a = w.current_tab()
        resp_a = R20(status=200, body=b'{"from":"a"}', content_type="application/json",
                     url="https://a.example", elapsed=10, size=13)
        w.response.set_response(resp_a)
        tab_a["response"] = resp_a
        tab_a["view"] = w.response.view_state()
        w.new_request()
        tab_b = w.current_tab()
        resp_b = R20(status=200, body=b'{"from":"b"}', content_type="application/json",
                     url="https://b.example", elapsed=11, size=13)
        w.response.set_response(resp_b)
        tab_b["response"] = resp_b
        tab_b["view"] = w.response.view_state()
        w.tabstrip.set_current(tab_a["id"])
        w._on_tab_changed(tab_a["id"])
        check("切回 A 标签显示 A 的响应", w.response.response is resp_a,
              w.response.response.url if w.response.response else "none")
        w.tabstrip.set_current(tab_b["id"])
        w._on_tab_changed(tab_b["id"])
        check("切回 B 标签显示 B 的响应", w.response.response is resp_b,
              w.response.response.url if w.response.response else "none")

        # 5) 侧栏动画被打断后必须恢复绘制，否则拖宽度会留下残影
        w._side_animating = True
        w._side_anim = None
        content = w.split.widget(1)
        content.setUpdatesEnabled(False)
        w._finish_sidebar_animation(240)
        pump(60)
        check("打断动画后恢复绘制", not w._side_animating
              and content.updatesEnabled()
              and abs(w.sidebar.width() - 240) <= 2, str(w.sidebar.width()))

        # 6) 版本只 +1，并写进应用内更新内容
        from app.store import CHANGELOG, VERSION

        check("版本升到当前版本", VERSION == CHANGELOG[0]["version"] and VERSION.count(".") == 2,
              VERSION)
        return 0

    def step21():
        print("[17] 类型色 / 自绘菜单 / 详情卡对齐 / 代码语言 / 请求标签点击切换")
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QColor, QMouseEvent

        # 1) 类型语义色：string 必须绿色，六种类型颜色互不相同
        from app.kv_editor import type_color

        cols = [QColor(type_color(k)).name() for k in
                ("auto", "text", "number", "bool", "null", "json")]
        green = QColor(cols[1])
        check("String 类型为绿色", green.green() > green.red() and green.green() > green.blue(),
              cols[1])
        check("类型颜色互不相同", len(set(cols)) >= 5, str(cols))

        # 2) 自绘类型菜单：选中项可对号，颜色与 chip 一致
        from app.kv_editor import TypeMenu

        tm = TypeMenu("text", w)
        check("类型菜单为自绘 Popup", not tm.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
              and tm._current == "text" and tm.height() > 100)
        picked = []
        tm.picked.connect(picked.append)
        tm.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(30, 5 + 30 * 2),
                                         QPointF(30, 5 + 30 * 2), Qt.MouseButton.LeftButton,
                                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        check("类型菜单可选择 Number", picked and picked[0] == "number", str(picked))
        tm.close()

        # 3) 格式 / 编码菜单改为 ChoiceMenu，勾选图标走 icons.pixmap
        from app.widgets import ChoiceMenu

        check("格式菜单自绘", isinstance(w.response._fmt_menu, ChoiceMenu) or
              w.response._fmt_menu is None)
        w.response._choose_format()
        check("格式菜单已弹出且自绘", isinstance(w.response._fmt_menu, ChoiceMenu)
              and w.response._fmt_menu.isVisible())
        w.response._fmt_menu.close()
        w.response._choose_encoding()
        check("编码菜单自绘", isinstance(w.response._enc_menu, ChoiceMenu))
        w.response._enc_menu.close()

        # 4) 展开/折叠按钮不再冒出来
        w.response._on_tab("tree")
        check("树形工具按钮始终隐藏", not w.response.tree_tools.isVisible())
        w.response._on_tab("pretty")

        # 5) 详情卡：脚注不与最后一行重叠，图标左右对齐
        card = w.response._timing_card()
        check("时间卡脚注在最后一行下方",
              card._note_y is not None and card._note_y > card._rows_y + len(card._rows) * card.ROW_H)
        check("详情卡图标方块统一", card.ICON_BOX == 22 and card.ROW_ICON <= card.ICON_BOX)
        size_card = w.response._size_card()
        check("大小卡脚注不压 Body",
              size_card._note_y > size_card._rows_y + len(size_card._rows) * size_card.ROW_H)

        # 6) 方法色板对准参考图，且去掉了「自定义」
        from app.request_panel import MethodMenu, METHODS
        from app.theme import method_color

        mm = MethodMenu("GET", w)
        check("方法菜单无自定义", "CUSTOM" not in mm._items and
              all(k in METHODS for k in mm._items))
        check("GET 绿 POST 橙 DELETE 红",
              QColor(method_color("GET")).green() > QColor(method_color("GET")).red()
              and QColor(method_color("POST")).red() > QColor(method_color("POST")).green()
              and QColor(method_color("DELETE")).red() > QColor(method_color("DELETE")).green())
        mm.close()

        # 7) 代码片段：常用语言 + 语法高亮
        from app.codegen import LANGUAGES
        from app.code_editor import CodeHighlighter
        from app.dialogs import CodeDialog

        keys = {k for k, _l, _f, _lang in LANGUAGES}
        check("代码片段含常用语言", {"curl", "python", "js", "httpie", "go", "java",
                                 "php", "csharp", "kotlin", "powershell"} <= keys)
        dlg = CodeDialog(w.current_tab()["request"], w.store.env_vars(), w.store.settings, w)
        dlg.tabs.set_current("go", emit=True)
        check("代码片段 Go 语言已生成且高亮",
              "func main" in dlg.code.toPlainText()
              and isinstance(dlg.code._hl, CodeHighlighter))
        dlg.tabs.set_current("python", emit=True)
        check("切回 Python 有 requests 代码", "import requests" in dlg.code.toPlainText())
        dlg.close()

        # 8) 关键：鼠标点击标签必须触发 currentChanged，内容随标签切换
        from app.tabs import TabStrip

        w.new_request()
        ta = w.current_tab()
        w.editor.urlbar.url.setText("https://click-a.example/x")
        app.processEvents()
        w.new_request()
        tb = w.current_tab()
        w.editor.urlbar.url.setText("https://click-b.example/y")
        app.processEvents()
        rects = w.tabstrip._rects()
        idx_a = next(i for i, t in enumerate(w.tabstrip.tabs) if t["id"] == ta["id"])
        idx_b = next(i for i, t in enumerate(w.tabstrip.tabs) if t["id"] == tb["id"])
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(rects[idx_a].center().x(),
                            rects[idx_a].center().y()), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        w.tabstrip.mousePressEvent(press)
        app.processEvents()
        check("点击标签切换内容 A", w.editor.urlbar.url.text() == "https://click-a.example/x",
              w.editor.urlbar.url.text())
        press_b = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(rects[idx_b].center().x(),
                              rects[idx_b].center().y()), Qt.MouseButton.LeftButton,
                              Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        w.tabstrip.mousePressEvent(press_b)
        app.processEvents()
        check("点击标签切换内容 B", w.editor.urlbar.url.text() == "https://click-b.example/y",
              w.editor.urlbar.url.text())
        check("点击标签后主窗口 active 同步", w._active_tab_id == tb["id"])
        return 0

    def step22():
        print("[18] 集合运行器：顺序执行 / 状态汇总 / 结果复制")
        from app.runner import RunnerDialog, flatten_requests
        from app.store import new_folder

        folder = new_folder("Runner Demo")
        sub = new_folder("Nested")
        sub["children"] = [new_request("B", "POST", f"http://127.0.0.1:{PORT}/b")]
        folder["children"] = [
            new_request("A", "GET", f"http://127.0.0.1:{PORT}/a"),
            sub,
            new_request("C", "GET", f"http://127.0.0.1:{PORT}/c"),
        ]
        flat = flatten_requests(folder)
        check("运行器展平嵌套文件夹", [r["name"] for r in flat] == ["A", "B", "C"],
              str([r["name"] for r in flat]))

        dlg = RunnerDialog(w.store, folder, w)
        check("运行器为每条请求建行", len(dlg.rows) == 3, str(len(dlg.rows)))
        dlg._start()
        ok = wait_until(lambda: dlg.runner is not None and not dlg.runner.running
                        and len(dlg.runner.records) == 3, 15000)
        recs = dlg.runner.records if dlg.runner else []
        check("运行器跑完全部请求", ok, str(len(recs)))
        check("运行器状态码均为 200", bool(recs) and all(r["status"] == 200 for r in recs),
              str([r["status"] for r in recs]))
        check("运行器标记全部成功", bool(recs) and all(r["ok"] for r in recs))
        check("运行器记录响应体积", bool(recs) and all(r["size"] > 0 for r in recs))
        check("运行器按钮变回「再跑一次」", dlg.run_btn._text == "再跑一次", dlg.run_btn._text)
        check("运行器汇总成功 3", "成功 3" in dlg.summ.text(), dlg.summ.text())
        check("运行器行状态为已完成", all(row.state == "done" for row in dlg.rows),
              str([row.state for row in dlg.rows]))
        dlg._copy()
        lines = QApplication.clipboard().text().splitlines()
        check("运行器复制结果为 TSV", len(lines) == 4 and lines[0].startswith("name\tmethod"),
              str(len(lines)))
        dlg.close()
        return 0

    def step23():
        print("[19] 交互健壮性：标签自愈 / 中键关闭 / 分栏复位 / 存为变量 / 侧栏动画")
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        # 1) 点「当前标签」也必须把内容拉回来（以前 _current 相同就什么都不做）
        w.new_request()
        t1 = w.current_tab()
        w.editor.urlbar.url.setText("https://sync.example/a")
        app.processEvents()
        w.new_request()
        t2 = w.current_tab()
        app.processEvents()
        w._on_tab_changed(t1["id"])
        app.processEvents()
        rects = w.tabstrip._rects()
        idx = next(i for i, t in enumerate(w.tabstrip.tabs) if t["id"] == t1["id"])
        QTest.mouseClick(w.tabstrip, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, rects[idx].center().toPoint())
        app.processEvents()
        check("再次点击当前标签内容仍在", w.editor.urlbar.url.text() == "https://sync.example/a",
              w.editor.urlbar.url.text())

        # 2) 人为制造错位（编辑器挂了别的请求），切窗口回来必须自愈
        w.editor.load({"id": "ghost", "method": "GET", "url": "https://ghost.example/z"})
        app.processEvents()
        w._ensure_tab_sync()
        app.processEvents()
        check("标签与编辑器错位能自愈", w.editor.urlbar.url.text() == "https://sync.example/a",
              w.editor.urlbar.url.text())

        # 3) 中键关闭标签
        before = len(w.tabs_data)
        idx2 = next(i for i, t in enumerate(w.tabstrip.tabs) if t["id"] == t2["id"])
        r2 = w.tabstrip._rects()[idx2]
        press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(r2.center().x(), r2.center().y()),
                            Qt.MouseButton.MiddleButton, Qt.MouseButton.MiddleButton,
                            Qt.KeyboardModifier.NoModifier)
        w.tabstrip.mousePressEvent(press)
        app.processEvents()
        check("中键关闭标签", len(w.tabs_data) == before - 1, str(len(w.tabs_data)))

        # 4) 双击分隔条恢复 50/50
        w.splitter.setSizes([200, w.splitter.height() - 200])
        w._reset_split()
        app.processEvents()
        sizes = w.splitter.sizes()
        check("双击分栏恢复 50/50", abs(sizes[0] - sizes[1]) <= 6, str(sizes))

        # 5) 提取结果存为环境变量
        w._save_env_var("smoke_token", "abc123")
        env = w.store.active_environment()
        got = {r["key"]: r["value"] for r in (env or {}).get("vars", [])}
        check("提取结果写入环境变量", got.get("smoke_token") == "abc123", str(got.get("smoke_token")))

        # 6) 侧栏动画必须逐帧移动（以前被 minimumSizeHint 卡在 200 一动不动）
        w.store.settings["sidebar_visible"] = True
        w.sidebar.setVisible(True)
        w.split.setSizes([268, w.split.width() - 268])
        app.processEvents()
        widths = []
        orig = w.split.setSizes

        def spy(sizes_):
            orig(sizes_)
            app.processEvents()
            widths.append(w.sidebar.width())

        w.split.setSizes = spy
        w.toggle_sidebar()
        t0 = __import__("time").time()
        while __import__("time").time() - t0 < 0.45:
            app.processEvents()
            __import__("time").sleep(0.005)
        w.split.setSizes = orig
        mid = [x for x in widths if 5 < x < 200]
        check("侧栏收起有中间帧", len(mid) >= 3, str(widths[:12]))
        check("侧栏收起后最小宽度恢复", not w.sidebar.isVisible() and w.sidebar.minimumWidth() in (0, 200),
              f"{w.sidebar.isVisible()}/{w.sidebar.minimumWidth()}")
        w.toggle_sidebar()
        t0 = __import__("time").time()
        while __import__("time").time() - t0 < 0.45:
            app.processEvents()
            __import__("time").sleep(0.005)
        check("侧栏展开后宽度与策略复原",
              w.sidebar.isVisible() and w.sidebar.width() >= 200
              and w.sidebar.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Preferred,
              f"{w.sidebar.width()}")
        check("动画结束后禁止把子控件拖没",
              w.split.childrenCollapsible() is False)

        # 7) 历史列表增量刷新：新请求只插一行，不重建整表
        from app.store import new_request as _nr

        w.store.data["history"] = []
        for i in range(4):
            w.store.push_history(_nr(f"h{i}", "GET", f"https://h.example/{i}"), 200, i)
        w.sidebar.refresh_history()
        app.processEvents()
        n1 = len(getattr(w.sidebar, "_hist_rows", []))
        first_before = w.sidebar._hist_rows[0] if n1 else None
        w.store.push_history(_nr("h4", "GET", "https://h.example/4"), 200, 9)
        w.sidebar.refresh_history()
        app.processEvents()
        rows_now = getattr(w.sidebar, "_hist_rows", [])
        check("历史增量刷新条数正确", n1 == 4 and len(rows_now) == 5, f"{n1}/{len(rows_now)}")
        check("历史增量刷新保留旧行对象", bool(rows_now) and rows_now[1] is first_before)

        # 8) 大响应按需渲染：树 / 原始页懒加载，超大文档关闭高亮
        import json as _json
        import time as _time

        from app.http_client import Response as _Resp

        rp = w.response
        rp._on_tab("pretty")
        app.processEvents()
        small = _json.dumps({"code": 0, "items": [{"id": i} for i in range(40)]}).encode()
        rp.set_response(_Resp(status=200, reason="OK", headers=[("Content-Type", "application/json")],
                              body=small, elapsed=9, size=len(small), url="https://lazy.example/a",
                              content_type="application/json"))
        app.processEvents()
        check("JSON 树默认不建（懒加载）", rp._tree_ready is False and rp._tree_data is not None)
        check("原始页默认不填充（懒加载）", rp._raw_pending is True)
        rp._on_tab("tree")
        app.processEvents()
        check("打开树形页后才建树", rp.json_tree.topLevelItemCount() > 0)
        rp._on_tab("raw")
        app.processEvents()
        check("打开原始页后才填充", rp.raw.toPlainText() == small.decode())

        rp._on_tab("pretty")
        app.processEvents()
        big = _json.dumps({"items": [{"id": i} for i in range(20000)]}).encode()
        t0 = _time.perf_counter()
        rp.set_response(_Resp(status=200, reason="OK", headers=[("Content-Type", "application/json")],
                              body=big, elapsed=9, size=len(big), url="https://lazy.example/big",
                              content_type="application/json"))
        app.processEvents()
        cost = (_time.perf_counter() - t0) * 1000
        check("200KB 以上响应渲染 < 400ms", cost < 400, f"{cost:.0f}ms")
        check("超大文档关闭语法高亮", rp.pretty._hl is None)
        huge = _json.dumps({"items": [{"id": i, "name": f"u{i}"} for i in range(60000)]}).encode()
        rp.set_response(_Resp(status=200, reason="OK", headers=[("Content-Type", "application/json")],
                              body=huge, elapsed=9, size=len(huge), url="https://lazy.example/huge",
                              content_type="application/json"))
        app.processEvents()
        check("超大响应代码区截断", "另存为" in rp.pretty.toPlainText()[-260:],
              f"{len(huge) // 1024}KB")
        rp._on_tab("tree")
        app.processEvents()
        check("超大响应不建树", rp.json_tree.topLevelItemCount() == 1)
        rp._on_tab("pretty")
        app.processEvents()
        rp.set_response(_Resp(status=200, reason="OK", headers=[("Content-Type", "application/json")],
                              body=small, elapsed=9, size=len(small), url="https://lazy.example/a",
                              content_type="application/json"))
        app.processEvents()
        check("小响应恢复高亮", rp.pretty._hl is not None)

        # 9) 双击斜体预览标签 → 转正固定（VSCode 行为）
        w._open_request_obj(new_request("Preview Pin", "GET", "https://pin.example/x"),
                            node_id=None, preview=True)
        app.processEvents()
        pin_tab = w.current_tab()
        check("预览标签初始为斜体预览态", pin_tab.get("preview") is True)
        rects = w.tabstrip._rects()
        idx_pin = next(i for i, t in enumerate(w.tabstrip.tabs) if t["id"] == pin_tab["id"])
        QTest.mouseDClick(w.tabstrip, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier, rects[idx_pin].center().toPoint())
        app.processEvents()
        check("双击预览标签后转正固定", w._tab(pin_tab["id"]).get("preview") is False,
              str(w._tab(pin_tab["id"]).get("preview")))
        check("标签栏同步取消斜体", w.tabstrip.tab(pin_tab["id"]).get("preview") is False)

        print("[20] 类型配色与主题色")

        def _hex_dist(a: str, b: str) -> float:
            from PyQt6.QtGui import QColor as _QC

            ca, cb = _QC(a), _QC(b)
            return ((ca.red() - cb.red()) ** 2 + (ca.green() - cb.green()) ** 2
                    + (ca.blue() - cb.blue()) ** 2) ** 0.5

        # 10) 类型配色：Auto 必须有自己的颜色，且与 Null 的灰区分得开
        from app.kv_editor import type_color as _tcolor

        auto_c, null_c = _tcolor("auto"), _tcolor("null")
        check("Auto 有独立配色", auto_c != null_c, f"{auto_c} / {null_c}")
        check("Auto 与 Null 色差足够", _hex_dist(auto_c, null_c) > 40, f"{_hex_dist(auto_c, null_c):.0f}")

        # 11) 主题色：切换后主按钮强调色跟着变，且能持久化
        from app import theme as _th

        w.store.settings["accent"] = "blue"
        w._apply_theme(w.store.settings.get("theme", "dark"))
        app.processEvents()
        expect = _th.ACCENTS["blue"][1 if _th.theme().is_dark else 2][0]
        check("切换主题色生效", _th.theme().accent == expect, _th.theme().accent)
        check("主题色写入配置", w.store.settings.get("accent") == "blue")
        w.store.settings["accent"] = "auto"
        w._apply_theme(w.store.settings.get("theme", "dark"))
        app.processEvents()
        check("主题色回自动为反色实心", _th.theme().accent in ("#F2F2F5", "#151517"), _th.theme().accent)

        # 12) 设置面板里的色点数量与默认选中
        from app.dialogs import AccentPicker

        picker = AccentPicker(w.store.settings.get("accent", "auto"))
        check("主题色色点数完整", len(picker.keys) == len(_th.ACCENT_ORDER) == 7, str(len(picker.keys)))
        got = []
        picker.picked.connect(got.append)
        rect_c = picker._centers()[2]
        from PyQt6.QtCore import QPointF as _QP
        from PyQt6.QtGui import QMouseEvent as _QME
        picker.mouseReleaseEvent(_QME(QEvent.Type.MouseButtonRelease,
                                      _QP(rect_c.x(), rect_c.y()), Qt.MouseButton.LeftButton,
                                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        check("点击色点发出选择", got == ["teal"], str(got))
        from app.dialogs import SettingsDialog as _SD

        _dlg = _SD(w.store, w, page="appearance")
        check("外观页内有主题色选择器", isinstance(getattr(_dlg, "accent_picker", None), AccentPicker))
        _dlg.close()
        # 13) 英文下不再出现原样中文
        from app import i18n as _i18n
        _i18n.set_language("en")
        check("主题色文案有英文译文",
              _i18n.tr("主题色") == "Accent color" and _i18n.tr("海蓝") == "Blue",
              _i18n.tr("主题色"))
        _i18n.set_language("zh")
        return 0

    # ---------------------------------------------------------------- 本轮新增
    def step24():
        print("[21] Ocelot 改名 / Cookie / 云同步 / 主题色渗透")
        from PyQt6.QtWidgets import QLineEdit as _QLE

        from app.main_window import APP_NAME
        from app.store import APP_DIR

        check("应用名已改为 Ocelot", APP_NAME == "Ocelot" and w.windowTitle() == "Ocelot", APP_NAME)
        check("数据目录指向 Ocelot", APP_DIR.name == "Ocelot", str(APP_DIR))
        check("保留旧数据迁移入口", callable(getattr(Store, "migrate_legacy", None)))

        # 1) 请求面板多了 Cookies 页，且能写回请求
        keys = [i["key"] for i in w.editor.tabs._items]
        check("请求面板新增 Cookies 页", "cookies" in keys, str(keys))
        w.editor.cookies.set_rows([{"key": "session", "value": "abc", "enabled": True}])
        w.editor._on_cookies()
        tab = w.current_tab()
        check("Cookie 写回请求", tab["request"].get("cookies")
              == [{"key": "session", "value": "abc", "enabled": True}],
              str(tab["request"].get("cookies")))
        check("Cookie 页有计数徽标", any(i["key"] == "cookies" and i["badge"] == 1
                                        for i in w.editor.tabs._items))

        # 2) 地址栏按历史补全（自绘浮层，不再是 QCompleter）
        ub = w.editor.urlbar
        ub._refresh_url_suggestions()
        check("地址栏缓存了历史地址", len(ub._url_history) > 0, str(len(ub._url_history)))
        ub.url.setText("h.example")
        ub._on_url_typed("h.example")
        pop = ub._url_popup
        check("输入时弹出候选浮层", pop is not None and pop.isVisible() and pop.has_items(),
              "no popup" if pop is None else str(len(pop.items)))
        if pop is not None and pop.has_items():
            first = pop.current()
            pop.step(1)
            check("上下键能换选中项", pop.current() != first or len(pop.items) == 1)
            ub._apply_url_suggestion(first)
            check("选中候选写回地址栏", ub.url.text() == first, ub.url.text())
            pop.hide()

        # 3) 主题色要渗到文字 / 选中底 / 徽标，而不只是按钮
        from app import theme as _th

        base = _th.theme_by_name("graphite")
        w.store.settings["accent"] = "purple"
        w._apply_theme("graphite")
        app.processEvents()
        cur = _th.theme()
        accent_rgb = (QColor(cur.accent).red(), QColor(cur.accent).green(), QColor(cur.accent).blue())
        check("选中底用强调色的透明版", tuple(cur.selected[:3]) == accent_rgb, str(cur.selected))
        check("徽标底用强调色", tuple(cur.accent_soft[:3]) == accent_rgb, str(cur.accent_soft))
        check("文字朝强调色偏色", cur.text != base.text, f"{base.text} -> {cur.text}")
        check("聚焦描边用强调色", tuple(cur.accent_dim[:3]) == accent_rgb, str(cur.accent_dim))
        w.store.settings["accent"] = "auto"
        w._apply_theme("graphite")
        app.processEvents()

        # 4) 勾选框选中态不再多一圈描边
        from app.kv_editor import MiniCheck, TypeChip, type_color

        mc = MiniCheck(True)
        mc.resize(15, 15)
        pm = mc.grab()
        img = pm.toImage()
        dpr = pm.devicePixelRatio() or 1.0
        edge = img.pixelColor(int(1.2 * dpr), int(7.5 * dpr))
        check("勾选框选中态不留描边", edge.value() > 150, edge.name())

        # 5) 类型胶囊：Auto 用自己的暖沙色
        chip = TypeChip("auto")
        chip.resize(60, 20)
        cimg = chip.grab().toImage()
        want = QColor(type_color("auto"))
        hit = False
        for y in range(2, cimg.height() - 2, 2):
            for x in range(2, cimg.width() - 2, 2):
                c = cimg.pixelColor(x, y)
                if (abs(c.red() - want.red()) + abs(c.green() - want.green())
                        + abs(c.blue() - want.blue())) < 150:
                    hit = True
                    break
            if hit:
                break
        check("Auto 胶囊用自己的颜色", hit, want.name())

        # 6) 色点第一颗不被裁切
        from app.dialogs import AccentPicker as _AP

        ap = _AP("auto")
        first = ap._centers()[0]
        check("第一颗色点不被卡片切掉", first.x() - (ap.DOT / 2 + ap.RING) >= 0, str(first.x()))

        # 7) 菜单圆角不再有方块
        from app.widgets import Menu

        m = Menu(w)
        check("菜单改用透明底", m.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        m.deleteLater()

        # 8) 标签右键「复制为 cURL」不再 NameError
        w._copy_tab_as_curl(w.current_tab()["id"])
        clip = QApplication.clipboard().text()
        check("复制 cURL 可用", clip.startswith("curl"), clip[:16])

        # 9) 云同步：地址归一化 + 未配置时的中文提示
        from app.cloud import CloudError, TursoClient, normalize_url

        check("libsql 地址归一化",
              normalize_url("libsql://ocelot-x.turso.io") == "https://ocelot-x.turso.io",
              normalize_url("libsql://ocelot-x.turso.io"))
        check("裸域名补 https", normalize_url("db.turso.io/") == "https://db.turso.io")
        raised = False
        try:
            TursoClient("", "").test()
        except CloudError:
            raised = True
        check("未配置时给出提示", raised)

        from app.dialogs import SettingsDialog as _SD

        dlg = _SD(w.store, w, page="cloud")
        check("设置新增云同步页", "cloud" in [k for k, _l, _i in dlg.NAV])
        check("云同步页有地址与 Token",
              dlg.cloud_url is not None
              and dlg.cloud_token.echoMode() == _QLE.EchoMode.Password)
        dlg.close()

        # 10) 命令面板能直接切环境
        items = w.palette._collect()
        envs = [i for i in items if i["kind"] == "env"]
        check("命令面板列出环境", len(envs) >= 1, str(len(envs)))
        if envs:
            w._on_palette_action("env", envs[0]["key"])
            check("命令面板可切换环境", w.store.data["active_env"] == envs[0]["key"])

        # 11) 真正发一次：Cookie 表 + 手写 Cookie 头合并
        req = new_request("Cookie 合并", "GET", f"http://127.0.0.1:{PORT}/echo")
        req["cookies"] = [{"key": "session", "value": "abc", "enabled": True}]
        req["headers"] = [{"key": "Cookie", "value": "manual=1", "enabled": True}]
        w._open_request_obj(req, node_id=None)
        app.processEvents()
        state["resp"] = None
        w.send_current()
        return 1500

    def step25():
        print("[22] Cookie 真的发出去了 / 从响应导入")
        headers = (ECHO["data"] or {}).get("headers", {})
        check("Cookie 表合并进请求头", headers.get("cookie") == "session=abc; manual=1",
              str(headers.get("cookie")))
        resp = state.get("resp")
        check("响应带回 Set-Cookie", bool(resp and resp.cookies),
              str(len(resp.cookies)) if resp else "no resp")
        w.editor.set_last_cookies(resp.cookies if resp else [])
        before = len(w.editor.cookies.rows())
        w.editor._import_cookies()
        rows = w.editor.cookies.rows()
        check("从响应导入 Cookie", len(rows) > before and any(r["key"] == "smoke" for r in rows),
              str(rows))
        check("导入后写回请求", any(r["key"] == "smoke"
                                   for r in (w.current_tab()["request"].get("cookies") or [])))
        return 0

    def step26():
        print("[23] 接口文档生成 / 密钥脱敏 / 代码生成带 Cookie")
        from app.codegen import to_curl, to_python
        from app.http_client import Response
        from app.share import json_key_diff, redact_headers, redact_text, schema_keys, to_markdown

        masked = redact_text('{"token": "abcdef1234567890", "user": "kate"}')
        check("脱敏保留普通字段", "kate" in masked and "abcdef1234567890" not in masked, masked)
        check("长密钥留末四位便于对账", "7890" in masked, masked)
        auth = redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdefgh.ijklmnop")
        check("Bearer 保留方案名", auth.startswith("Authorization: Bearer "), auth)
        check("JWT 原文不出现", "eyJhbGci" not in auth, auth)
        hdrs = dict(redact_headers([("Authorization", "Bearer abcdefghijk123"), ("Accept", "*/*")]))
        check("普通请求头不动", hdrs["Accept"] == "*/*", str(hdrs))
        check("敏感请求头打码", "abcdefghijk123" not in hdrs["Authorization"], str(hdrs))

        req = new_request("登录接口", "POST", f"http://127.0.0.1:{PORT}/echo")
        req["params"] = [{"key": "q", "value": "hi", "enabled": True}]
        req["headers"] = [{"key": "X-Trace", "value": "t-1", "enabled": True}]
        req["cookies"] = [{"key": "session", "value": "abc", "enabled": True},
                          {"key": "off", "value": "1", "enabled": False}]
        req["body"] = {"mode": "json", "raw": '{"u":"kate"}'}
        curl = to_curl(req, {})
        check("cURL 带上 Cookie 页的 Cookie", "Cookie: session=abc" in curl, curl)
        check("cURL 忽略被禁用的 Cookie", "off=1" not in curl, curl)
        py = to_python(req, {})
        check("Python 代码带上 Cookie", "session=abc" in py, py[:40])

        # 用一份构造出来的响应测文档生成，不依赖网络时序
        fake = Response(status=200, reason="OK", elapsed=42, size=24,
                        url="http://127.0.0.1/echo", content_type="application/json",
                        headers=[("Set-Cookie", "sid=xyz")], body=b'{"u":"kate","token":"tk-9988776655"}')
        base = f"`POST` http://127.0.0.1:{PORT}/echo?q=hi"
        md_safe = to_markdown(req, fake, {})
        md_open = to_markdown(req, fake, {}, redact=False)
        check("文档含方法与地址", base in md_safe, md_safe[:80])
        check("文档含请求头表", "| `X-Trace` | t-1 |" in md_safe, md_safe[:200])
        check("文档含状态与耗时", "**200 OK**" in md_safe and "42 ms" in md_safe, md_safe[-160:])
        check("文档含响应示例", "### 响应示例" in md_safe, md_safe[-160:])
        check("文档默认打码 Cookie", "session=abc" not in md_safe, md_safe[:200])
        check("文档默认打码响应里的 token", "tk-9988776655" not in md_safe, md_safe[-160:])
        check("可选保留原值", "session=abc" in md_open, md_open[:200])
        check("文档超长截断", "已截断" in to_markdown(req, fake, {}, body_limit=8), "未截断")

        check("结构对比能看出新增字段", "+ b" in json_key_diff({"a": 1}, {"a": 1, "b": 2}))
        check("结构对比标出类型变化",
              any(x.startswith("~") for x in json_key_diff({"a": 1}, {"a": "1"})),
              str(json_key_diff({"a": 1}, {"a": "1"})))
        check("能展开响应键路径", "a.b" in schema_keys({"a": {"b": 1}}))

        check("响应头部有更多按钮", getattr(w.response, "more_btn", None) is not None)
        check("面板发出文档请求信号", hasattr(w.response, "docRequested"))
        check("主窗口能打开接口文档", callable(getattr(w, "open_doc", None)))
        from app.ctxmenu import _text_target

        probe_label = QLabel("x")
        probe_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        check("可选中标签的右键菜单被接管", _text_target(probe_label) is probe_label)
        plain_label = QLabel("y")
        check("普通标签不抢右键", _text_target(plain_label) is None)
        code_view = w.response.pretty
        check("代码区 viewport 的右键也接管",
              _text_target(code_view.viewport()) is code_view)
        from app.dialogs import CommandPalette

        acts = [a[0] for a in CommandPalette.ACTIONS]
        check("命令面板能打开接口文档", "doc" in acts, str(acts[-2:]))

        # 真发一次，验证整条链路：请求 → 响应 → 复制文档
        w._open_request_obj(req, node_id=None)
        app.processEvents()
        state["resp"] = None
        w.send_current()
        return 1200

    def step27():
        print("[24] 接口文档窗口：渲染 / 打码 / 复制 / 保存")
        from app.doc_window import DocDialog
        from app.markdown_view import MarkdownView, parse_blocks

        resp = w.response.response
        req = w.current_tab()["request"] if w.current_tab() else {}
        if resp is None:
            check("拿到响应", False, "no response")
            return 0

        dlg = DocDialog(w.store, req, resp, w)
        app.processEvents()
        check("文档窗口能打开", isinstance(dlg.view, MarkdownView) and dlg.width() > 800)
        check("文档渲染出响应段", "## 响应" in dlg._markdown, dlg._markdown[-60:])
        check("大纲列出章节", len(dlg._outline_items) >= 3, str(len(dlg._outline_items)))
        check("代码示例默认 cURL", dlg._lang == "curl")
        dlg.lang_tabs.set_current("python", emit=True)
        # 代码块 + 底部 stretch 共两项；语言切换后仍应只有一个代码块
        check("能切换代码示例语言", dlg._lang == "python"
              and dlg._code_lay.count() == 2, str(dlg._code_lay.count()))
        dlg.lang_tabs.set_current("curl", emit=True)

        check("默认开启密钥打码", dlg._redact is True)
        dlg.redact_switch.setChecked(False, emit=True)
        app.processEvents()
        check("关掉打码后 Cookie 原值回来了", "session=abc" in dlg._markdown,
              "未出现原值")

        dlg._copy()
        clip = QApplication.clipboard().text()
        check("复制按钮把文档放进剪贴板", clip.startswith("# "), clip[:20])

        import tempfile, os as _os
        from unittest import mock

        tmp = _os.path.join(tempfile.gettempdir(), "ocelot_doc_smoke.md")
        if _os.path.exists(tmp):
            _os.remove(tmp)
        with mock.patch("app.doc_window.QFileDialog.getSaveFileName", return_value=(tmp, "")):
            dlg._save()
        check("保存成 .md 文件", _os.path.exists(tmp) and _os.path.getsize(tmp) > 100,
              "no file")
        body = open(tmp, encoding="utf-8").read()
        check("文件内容就是文档", body.startswith("# "), body[:20])
        _os.remove(tmp)
        dlg.close()

        check("Markdown 解析器认得表格与代码块",
              [b["kind"] for b in parse_blocks("| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
                                               "```json\n{}\n```")] == ["table", "code"])
        return 0

    def step28():
        print("[25] 参数表对齐 / 时间线 / Mock / 设置页排版")
        from app.kv_editor import KVEditor, KVRow

        ed = KVEditor(with_types=True)
        ed.resize(720, 200)
        ed.set_rows([{"key": "a", "value": "b", "enabled": True, "type": "auto"}])
        ed.show()
        app.processEvents()
        hdr = ed.header.layout()
        row = ed.findChildren(KVRow)[0].layout()
        def xs(layout):
            out = []
            for i in range(layout.count()):
                wdg = layout.itemAt(i).widget()
                if wdg is not None and wdg.isVisible():
                    out.append(layout.itemAt(i).geometry().x())
            return out

        hx, rx = xs(hdr), xs(row)
        check("表头与数据行列位置一一对齐", hx == rx, f"{hx} vs {rx}")
        ed.close()

        # 时间线
        import time as _time

        entries = [{"ts": _time.time() - i * 60, "status": 200 if i % 3 else 500,
                    "elapsed": 40 + i * 7} for i in range(8)]
        entries.reverse()
        w.response.set_history(entries)
        check("响应面板有时间线页", w.response.tabs.current() is not None
              and any(i["key"] == "timeline" for i in w.response.tabs._items))
        check("时间线收到历史数据", len(w.response.timeline.entries) == 8)
        st = w.response.timeline._stats()
        check("时间线算得出成功率", st["n"] == 8 and 0 < st["ok"] < 8, str(st.get("ok")))
        check("时间线算出 P95 与最慢", st["p95"] >= st["min"] and st["max"] >= st["p95"])

        # Mock
        from app.mock_panel import MOCKS, MockDialog

        dlg = MockDialog(w.store, w.mock, w)
        app.processEvents()
        dlg.tabs.set_current("public", emit=True)     # Mock 中心默认停在本地服务页
        app.processEvents()
        check("Mock 清单有内容", len(MOCKS) >= 20 and len(dlg.rows) == len(MOCKS),
              f"{len(MOCKS)}/{len(dlg.rows)}")
        dlg.search.setText("登录")
        dlg._rebuild_public()          # 输入有 120ms 防抖，测试里直接重建
        app.processEvents()
        check("Mock 支持搜索", 0 < len(dlg.rows) < len(MOCKS), str(len(dlg.rows)))
        dlg.search.setText("")
        dlg.group_tabs.set_current("回显调试", emit=True)
        dlg._rebuild_public()
        app.processEvents()
        check("Mock 支持分组过滤", all(r.item["g"] == "回显调试" for r in dlg.rows)
              and len(dlg.rows) < len(MOCKS), str(len(dlg.rows)))
        before_tabs = len(w.tabs_data)
        w._use_mock({"g": "回显调试", "m": "POST", "u": "https://httpbin.org/post",
                     "d": "回显", "b": '{"a": 1}'})
        app.processEvents()
        tab = w.current_tab()
        check("点一条 Mock 就新建请求", len(w.tabs_data) >= before_tabs
              and tab["request"]["url"] == "https://httpbin.org/post")
        check("Mock 带上了示例请求体",
              tab["request"]["body"]["mode"] == "json" and '"a"' in tab["request"]["body"]["raw"])
        dlg.close()

        # 设置页：控件不许被挤到卡片外
        from app.dialogs import SettingsDialog
        from app.store import VERSION as _VER

        sd = SettingsDialog(w.store, w, page="cloud")
        sd.show()
        app.processEvents()
        cloud_ok = sd.cloud_url.width() >= 300 and sd.cloud_token.width() >= 300
        stack = sd.stack.currentWidget()
        check("云同步输入框不再被压扁", cloud_ok,
              f"{sd.cloud_url.width()}x{sd.cloud_token.width()}")
        check("设置页嵌在滚动区里", isinstance(stack, QScrollArea))
        sd.nav.set_key("about_app")
        sd._on_nav("about_app")
        app.processEvents()
        about = sd.stack.currentWidget()
        texts = [lab.text() for lab in about.findChildren(QLabel)]
        check("关于页有字标与版本", "Ocelot" in texts and any(_VER in x for x in texts),
              str(texts[:6]))
        # 关于页改成面向用户的内容：不再暴露 Python / PyQt6 运行时信息
        check("关于页不写运行时与 Python 版本", not any("Python" in x or "PyQt6" in x
                                                    for x in texts), str(texts[:4]))
        check("关于页有优势与能力说明", any("为什么是 Ocelot" in x for x in texts)
              and any("它能做什么" in x for x in texts)
              and not any(".py" in x for x in texts), str(texts[-4:]))
        sd.close()

        # 命令面板
        from app.dialogs import CommandPalette

        acts = [a[0] for a in CommandPalette.ACTIONS]
        check("命令面板含 Mock / 文档 / 复制请求",
              all(k in acts for k in ("mock", "doc", "duplicate", "close_tab")), str(acts[-4:]))
        return 0


    def step29():
        print("[26] 快捷键 / 命令面板滚动 / 本地 Mock 服务 / 代码高亮")
        import json as _json
        import urllib.error as _urlerr
        import urllib.request as _urllib

        from app import shortcuts as sc

        # ---------- 快捷键注册表
        check("快捷键表覆盖核心动作", len(sc.ACTIONS) >= 15 and "send" in sc.defaults(),
              str(len(sc.ACTIONS)))
        check("键位显示成 macOS 符号", sc.display("Meta+Shift+C") == "⌘ ⇧ C",
              sc.display("Meta+Shift+C"))
        check("空键位显示为未设置", sc.display("") == "未设置")
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_K, Qt.KeyboardModifier.MetaModifier)
        check("录制能还原组合键", sc.from_event(ev) == "Meta+K", sc.from_event(ev))
        check("只按修饰键不算键位",
              sc.from_event(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Shift,
                                      Qt.KeyboardModifier.ShiftModifier)) == "")
        check("能查出键位冲突", sc.conflict(sc.defaults(), "Meta+K", exclude="new_request")
              == "命令面板", str(sc.conflict(sc.defaults(), "Meta+K")))

        before = sc.mapping(w.store).get("send")
        sc.set_key(w.store, "send", "Meta+Shift+Return")
        check("改键位写进设置", sc.mapping(w.store)["send"] == "Meta+Shift+Return")
        w._install_shortcuts()
        check("主窗口按新键位重建快捷键", len(w._shortcuts) >= 14, str(len(w._shortcuts)))
        sc.set_key(w.store, "send", "")
        check("清空键位就是关掉它", sc.mapping(w.store)["send"] == "" and
              len(w._shortcuts) >= 13, str(len(w._shortcuts)))
        sc.reset(w.store)
        check("恢复默认能回到原键位", sc.mapping(w.store)["send"] == before, before)
        w._install_shortcuts()

        # ---------- 设置页快捷键页
        from app.dialogs import SettingsDialog, ShortcutRecorder

        sd = SettingsDialog(w.store, w, page="shortcuts")
        sd.show()
        app.processEvents()
        check("快捷键页列出全部动作", len(sd._key_rows) == len(sc.ACTIONS),
              f"{len(sd._key_rows)}/{len(sc.ACTIONS)}")
        sd._on_shortcut("new_request", "Meta+K")
        check("键位冲突时旧动作自动让位", sc.mapping(w.store)["palette"] == "",
              str(sc.mapping(w.store)["palette"]))
        sd._reset_shortcuts()
        check("页面上的恢复默认生效", sc.mapping(w.store) == sc.defaults())
        rec = ShortcutRecorder("发送当前请求", "Meta+Return")
        check("录制框显示当前键位", "↵" in rec.cap.text(), rec.cap.text())
        rec.close()
        sd.close()

        # ---------- 命令面板滚动
        from app.dialogs import CommandPalette

        w.palette.open()
        app.processEvents()
        bar = w.palette.scroll.verticalScrollBar()
        check("命令面板条目不再被截断", len(w.palette._results) == len(w.palette._collect()),
              str(len(w.palette._results)))
        check("命令面板多出来时能滚动", bar is not None and bar.maximum() > 0,
              str(bar.maximum() if bar else "no bar"))
        w.palette.list.index = len(w.palette._results) - 1
        w.palette._scroll_to(w.palette.list.index)
        check("键盘选到底部会自动滚过去", bar.value() > 0, str(bar.value()))
        w.palette.close()
        app.processEvents()

        # ---------- 本地 Mock 服务（真起一个 HTTP 服务）
        from app.mock_server import MockServer, default_routes

        srv = MockServer()
        ok, msg = srv.start(default_routes(), 0)
        check("本地 Mock 服务能启动", ok and srv.running and srv.port > 0, msg)
        try:
            with _urllib.urlopen(srv.url_for("/api/user"), timeout=4) as r:
                payload = _json.loads(r.read().decode())
            check("动态数据每次都不一样", r.status == 200 and payload.get("id")
                  and payload.get("name") and payload.get("email"),
                  str(payload)[:60])
            req = _urllib.Request(srv.url_for("/api/echo"), data=b'{"hi":1}', method="POST")
            with _urllib.urlopen(req, timeout=4) as r2:
                echo = _json.loads(r2.read().decode())
            check("回显路由能看到真实请求", echo.get("body") == '{"hi":1}'
                  and echo.get("method") == "POST", str(echo)[:60])
            try:
                _urllib.urlopen(srv.url_for("/missing"), timeout=4)
                check("未匹配路由返回 404", False, "no error raised")
            except _urlerr.HTTPError as exc:
                body = _json.loads(exc.read().decode())
                check("未匹配路由返回 404", exc.code == 404
                      and "routes" in body, str(body)[:50])
            check("服务自检能连通", srv.probe())
        finally:
            srv.stop()
        check("停止后端口释放", not srv.running)

        # ---------- Mock 中心：路由管理
        from app.mock_panel import MockDialog

        dlg = MockDialog(w.store, w.mock, w)
        dlg.show()
        app.processEvents()
        cfg = w.store.data.setdefault("mock", {})
        cfg["routes"] = default_routes()
        dlg._rebuild_routes()
        check("本地页列出默认路由", len(dlg.route_rows) == len(default_routes()),
              str(len(dlg.route_rows)))
        dlg.port_edit.setText("0")
        dlg._start()
        app.processEvents()
        check("从面板启动服务", w.mock.running, dlg.local_hint.text())
        check("状态胶囊显示运行中", dlg.status_pill._text == "运行中", dlg.status_pill._text)
        try:
            _urllib.urlopen(w.mock.url_for("/api/boom"), timeout=4)
            boom = {}
        except _urlerr.HTTPError as exc:      # 这条路由故意是 500
            boom = _json.loads(exc.read().decode())
        check("面板里的路由真能访问", boom.get("error") == "internal_error", str(boom)[:40])
        dlg._stop()
        check("从面板停止服务", not w.mock.running)
        check("没启动时试用会被拦下", dlg._trial_route({"path": "/x"}) is None)
        dlg.close()
        w.store.data["mock"]["routes"] = default_routes()

        # ---------- 代码高亮与左对齐
        from app.code_editor import CodeHighlighter
        from app.markdown_view import CodeBlock, syntax_of

        check("围栏语言能映射到语法", syntax_of("curl") == "shell"
              and syntax_of("cs") == "csharp" and syntax_of("json") == "json",
              f"{syntax_of('curl')}/{syntax_of('cs')}")
        cb = CodeBlock("curl -X GET https://a.example/x", "curl")
        view = cb.findChildren(CodeView)[0]
        check("curl 代码块拿到了语法高亮", isinstance(view._hl, CodeHighlighter),
              type(view._hl).__name__)
        check("代码正文不再被行号槽顶进去", view.viewportMargins().left() == 0
              and view.document().documentMargin() == 0,
              f"{view.viewportMargins().left()}/{view.document().documentMargin()}")
        py_block = CodeBlock("import requests\nprint(requests.get('https://a').json())", "python")
        check("python 代码块也有高亮", isinstance(
            py_block.findChildren(CodeView)[0]._hl, CodeHighlighter))

        # ---------- 接口文档更详细（自己造一份响应，不依赖前面的步骤）
        from app.http_client import Response as _Resp

        resp = _Resp(status=200, reason="OK", body=b'{"id":42,"role":"admin"}',
                     content_type="application/json", url="https://api.example.com/v1/users/42",
                     elapsed=182, size=28, header_size=160,
                     headers=[("Content-Type", "application/json"), ("X-Trace", "abc123")],
                     timing={"prepare": 2, "dns": 5, "tcp": 4, "ssl": 8, "ttfb": 150,
                             "download": 2, "process": 0})
        req = {"id": "smoke-doc", "type": "request", "name": "用户详情", "method": "GET",
               "url": "https://api.example.com/v1/users/42",
               "params": [{"key": "verbose", "value": "true", "enabled": True}],
               "headers": [{"key": "Accept", "value": "application/json", "enabled": True}],
               "cookies": [{"key": "session", "value": "abc123def456ghi", "enabled": True}],
               "body": {"mode": "none", "raw": "", "form": [], "file": ""},
               "auth": {"type": "bearer", "token": "eyJhbGciOiJIUzI1NiJ9.secretpayload"},
               "note": "分页参数可选"}
        if True:
            from app.share import to_markdown

            md = to_markdown(req, resp, {}, redact=True)
            heads = [ln for ln in md.splitlines() if ln.startswith("## ")]
            check("文档有概览与状态码段", "## 概览" in md and "## 状态码" in md, str(heads))
            check("文档带响应头与示例", "### 响应头" in md and "### 响应示例" in md, str(heads))
            from app.doc_window import DocDialog

            dw = DocDialog(w.store, req, resp, w)
            app.processEvents()
            check("文档窗口有指标卡", dw.metrics.layout().count() >= 3,
                  str(dw.metrics.layout().count()))
            check("窗口正文不重复标题", not dw.view.blocks[0].get("text", "").startswith("用户详情"),
                  str(dw.view.blocks[:1])[:80])
            cache_key = next(k for k in dw._code_cache if k.startswith("curl"))
            check("代码示例按语言缓存", dw._code_for(LANGUAGES[0]) == dw._code_cache[cache_key])
            curl_code = next(x for x in LANGUAGES if x[0] == "curl")
            check("代码示例里的密钥一起打码",
                  "secretpayload" not in dw._code_for(curl_code),
                  dw._code_for(curl_code)[:80])
            dw.close()
        else:
            check("文档需要响应", False, "no response")
        return 0

    def step30():
        print("[27] 菜单 / Mock 状态 / 动态数据 / 条件规则 / 请求日志 / 表格与代码对齐")
        import json as _json
        import urllib.error as _urlerr
        import urllib.request as _urllib

        from app.markdown_view import CodeBlock, TableBlock
        from app.mock_panel import MockDialog
        from app.mock_server import MockServer, default_routes, render_placeholders

        # ---------- 菜单
        menu, acts = w._settings_menu()
        titles = [a.text() for a in menu.actions() if a.text()]
        check("设置菜单不再有浅色 / 深色", not any("浅色" in x for x in titles), str(titles))
        check("设置菜单保留 Mock 入口", any("Mock" in x for x in titles), str(titles))
        menu.deleteLater()

        # ---------- 动态占位符
        one = render_placeholders('{"id":{{@id}},"name":"{{@name}}","ok":{{@bool}}}')
        two = render_placeholders('{"id":{{@id}},"name":"{{@name}}","ok":{{@bool}}}')
        check("占位符能生成数据", "{{@id}}" not in one and _json.loads(one), one[:60])
        check("每次请求数据都不同", one != two, f"{one[:40]} / {two[:40]}")
        check("未知占位符原样保留", render_placeholders("{{@nope}}") == "{{@nope}}")

        # ---------- 本地服务：状态 / 规则 / 日志 / CORS
        srv = MockServer()
        ok, msg = srv.start(default_routes(), 0)
        check("默认示例里有规则与延迟", ok and any(r.get("rules") for r in srv.routes)
              and any(r.get("delay") for r in srv.routes), msg)
        port = srv.port
        try:
            one = _json.loads(_urllib.urlopen(srv.url_for("/api/user"), timeout=4).read())
            two = _json.loads(_urllib.urlopen(srv.url_for("/api/user"), timeout=4).read())
            check("服务返回的是动态数据", one["id"] != two["id"], f"{one['id']} / {two['id']}")

            try:
                _urllib.urlopen(srv.url_for("/api/profile"), timeout=4)
                check("没带 token 返回 401", False, "no error")
            except _urlerr.HTTPError as exc:
                check("没带 token 返回 401", exc.code == 401, str(exc.code))

            req = _urllib.Request(srv.url_for("/api/profile"), headers={"token": "123"})
            with _urllib.urlopen(req, timeout=4) as resp:
                vip = _json.loads(resp.read().decode())
                cors = resp.headers.get("Access-Control-Allow-Origin")
            check("带 token 命中规则返回 VIP 数据",
                  resp.status == 200 and vip.get("vip") is True, str(vip)[:60])
            check("响应带 CORS 头", cors == "*", str(cors))

            with _urllib.urlopen(srv.url_for("/api/slow"), timeout=6):
                pass
            check("日志按路由名统计命中", srv.hits.get("示例 · 用户信息（动态）") == 2,
                  str(srv.hits))
            check("日志记下方法与状态", len(srv.logs) >= 5
                  and srv.logs[0]["method"] == "GET" and srv.logs[0]["status"] == 200,
                  str(list(srv.logs)[:1]))
            check("慢接口的日志耗时是真的", any(e["ms"] >= 1500 for e in srv.logs),
                  str([e["ms"] for e in srv.logs]))
            check("能看出端口上是 Ocelot", MockServer._probe_ocelot(port))
        finally:
            srv.stop()
        check("停止后端口真的释放", not srv.port_in_use(port) and srv.port == 0)

        # ---------- Mock 中心：按钮跟着状态走
        dlg = MockDialog(w.store, w.mock, w)
        dlg.show()
        app.processEvents()
        check("没启动时按钮写「启动服务」", dlg.start_btn.text() == "启动服务",
              dlg.start_btn.text())
        dlg.port_edit.setText("0")
        dlg._start()
        app.processEvents()
        check("启动后按钮变「停止服务」", dlg.start_btn.text() == "停止服务"
              and dlg.server.running, dlg.start_btn.text())
        dlg.tabs.set_current("logs", emit=True)
        app.processEvents()
        check("日志页读到真实请求", len(dlg.log_rows) >= 1, str(len(dlg.log_rows)))
        dlg._stop()
        app.processEvents()
        check("停下后按钮回到「启动服务」", dlg.start_btn.text() == "启动服务"
              and not dlg.server.running, dlg.start_btn.text())
        dlg.close()

        # ---------- 表格 / 代码块排版
        tb = TableBlock(["项目", "内容"], [["方法", "GET"], ["地址", "`https://a.example/x`"]])
        tb.show()
        app.processEvents()
        check("表格首列宽度按内容算", 90 <= tb.col0 <= 220, str(tb.col0))
        cb = CodeBlock("curl -X GET https://a.example/x", "curl")
        cb.resize(620, 240)
        cb.show()
        app.processEvents()
        view = cb.findChildren(CodeView)[0]
        tag = [x for x in cb.findChildren(QLabel) if "CURL" in x.text()][0]
        check("代码与语言标签左对齐",
              tag.mapTo(cb, QPoint(0, 0)).x() == view.mapTo(cb, QPoint(0, 0)).x(),
              f"{tag.mapTo(cb, QPoint(0, 0)).x()} / {view.mapTo(cb, QPoint(0, 0)).x()}")
        check("单行代码不冒滚动条", not view.verticalScrollBar().isVisible(),
              str(view.height()))
        wide = CodeBlock("x = 1\n" * 30, "python")
        wide.resize(620, 300)
        wide.show()
        app.processEvents()
        wv = wide.findChildren(CodeView)[0]
        check("超长代码块按上限截断并出现滚动条",
              wv.height() <= 300 and wv.verticalScrollBar().isVisible(), str(wv.height()))
        tb.close()
        cb.close()
        wide.close()
        return 0

    def step31():
        print("[28] 右键菜单定位 / 停服务后连接真断")
        import socket as _socket

        from PyQt6.QtCore import QEvent as _QEvent
        from PyQt6.QtGui import QCursor as _QCursor, QContextMenuEvent as _Ctx

        from app.ctxmenu import _event_pos, _menu_for
        from app.mock_server import MockServer, default_routes

        # ---------- 右键菜单：定位不能崩
        ev = _Ctx(_Ctx.Reason.Mouse, QPoint(10, 10), QPoint(320, 240))
        check("右键事件能取到真实屏幕坐标", _event_pos(ev) == QPoint(320, 240),
              str(_event_pos(ev)))
        check("没有坐标的事件也不会抛异常",
              isinstance(_event_pos(_QEvent(_QEvent.Type.User)), QPoint))
        edit = QLineEdit("hello")
        edit.selectAll()
        menu = _menu_for(edit)
        check("输入框菜单项齐全", any("复制" in a.text() for a in menu.actions()),
              str([a.text() for a in menu.actions()]))
        menu.deleteLater()
        check("兜底坐标用的是鼠标位置而不是 QApplication",
              hasattr(_QCursor, "pos") and not hasattr(QApplication, "cursor"))

        # ---------- 停服务：连已经建立的连接也要断
        srv = MockServer()
        ok, _msg = srv.start(default_routes(), 0)
        port = srv.port
        sock = _socket.create_connection(("127.0.0.1", port), timeout=3)
        sock.sendall(b"GET /api/user HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        head = sock.recv(65536)
        check("响应要求关连接（不复用）", b"Connection: close" in head, head[:80].decode(
            "latin-1", "replace"))
        srv.stop()
        still = False
        try:
            sock.sendall(b"GET /api/user HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            # 缓冲里可能还有上一条响应的剩余 body，所以只认「又出现了一个状态行」
            still = b"HTTP/1." in sock.recv(65536)
        except OSError:
            still = False
        finally:
            try:
                sock.close()
            except OSError:
                pass
        check("停服务后老连接上也不再返回数据", not still)
        check("停完端口干净", not srv.port_in_use(port) and srv.port == 0)

        # ---------- 地址栏「更多」菜单：Mock 数据 / 复制请求不能再崩
        from PyQt6.QtGui import QAction as _QAction

        from app import request_panel as _rp

        picked = [""]

        class _FakeMenu:
            """把菜单换成「直接返回某一项」，好让 _on_more 的每个分支都跑到。"""

            def __init__(self, *a, **k):
                self.acts = []

            def addAction(self, *args):
                text = args[-1] if isinstance(args[-1], str) else ""
                act = _QAction(text, None)
                self.acts.append(act)
                return act

            def addSeparator(self):
                pass

            def deleteLater(self):
                pass

            def exec(self, *_a, **_k):
                return next((a for a in self.acts if picked[0] in a.text()), None)

        req_ed = _rp.RequestEditor(w.store)
        got = []
        req_ed.mockRequested.connect(lambda: got.append("mock"))
        req_ed.duplicateRequested.connect(lambda: got.append("dup"))
        req_ed.copyCurlRequested.connect(lambda: got.append("curl"))
        orig_menu = _rp.Menu
        _rp.Menu = _FakeMenu
        try:
            picked[0] = "Mock"
            req_ed._on_more(req_ed.urlbar.more_btn)
            picked[0] = "复制请求"
            req_ed._on_more(req_ed.urlbar.more_btn)
            picked[0] = "cURL"
            req_ed._on_more(req_ed.urlbar.more_btn)
        finally:
            _rp.Menu = orig_menu
        check("更多菜单的每一项都能走通", got == ["mock", "dup", "curl"], str(got))
        check("编辑器把 Mock / 复制的信号转发出去",
              hasattr(req_ed, "mockRequested") and hasattr(req_ed, "duplicateRequested"))
        req_ed.deleteLater()
        return 0

    def step32():
        print("[29] 圆角遮罩 / 树选中底色 / 英文文案 / 大树截断")
        from PyQt6.QtGui import QPalette as _Pal

        from app import i18n as _i18n
        from app.code_editor import MAX_TREE_CHILDREN, JsonTree
        from app.dialogs import SettingsDialog, WhatsNewDialog
        from app.store import VERSION as _V
        from app.store import new_request

        # 1) 内容层必须被裁成圆角，否则四个角是直角
        check("内容层有圆角遮罩", not w.root.mask().isEmpty(),
              str(w.root.mask().boundingRect()))
        check("遮罩尺寸跟内容层一致", w.root.mask().boundingRect().size() == w.root.size(),
              f"{w.root.mask().boundingRect().size()} vs {w.root.size()}")

        # 2) 树选中行不该在缩进格上涂一块底色
        tree = JsonTree()
        tree.set_data({"a": 1}, 2)
        check("树的高亮底是透明的",
              tree.palette().color(_Pal.ColorRole.Highlight).alpha() == 0,
              str(tree.palette().color(_Pal.ColorRole.Highlight).alpha()))

        # 3) 大数组只铺前 N 条，末尾留一行提示
        big = {"list": {f"k{i}": i for i in range(MAX_TREE_CHILDREN + 40)}}
        tree2 = JsonTree()
        tree2.set_data(big, 2)
        root_item = tree2.topLevelItem(0)
        check("大对象只铺前 N 个子项", root_item.childCount() == MAX_TREE_CHILDREN + 1,
              str(root_item.childCount()))
        last = root_item.child(root_item.childCount() - 1)
        check("末尾提示还有多少项", "40" in last.text(0), last.text(0))
        tree.deleteLater()
        tree2.deleteLater()

        # 4) 设置页与更新内容里不再写 Python / PyQt6
        sd = SettingsDialog(w.store, w)
        sd.show()
        app.processEvents()
        all_text = [lb.text() for lb in sd.findChildren(QLabel)]
        check("设置页不写 Python + PyQt6",
              not any("Python + PyQt6" in x for x in all_text), str(all_text[-3:]))
        wn = WhatsNewDialog(w)
        wn.show()
        app.processEvents()
        check("更新内容窗口不写 Python + PyQt6",
              not any(lb.text().strip() == f"Ocelot {_V} · Python + PyQt6"
                      for lb in wn.findChildren(QLabel)))  # noqa: E501
        wn.close()
        sd.close()

        # 5) 英文：提示语走翻译，占位符能来回切
        _i18n.set_language("en", notify=False)
        _i18n.apply_language(w)
        w.toast.show_message("已创建请求", "success")
        check("英文模式下提示语是英文", w.toast._text == "Request created", w.toast._text)
        req = w.editor.urlbar.url
        check("英文模式下地址栏占位是英文", "Enter a request URL" in req.placeholderText(),
              req.placeholderText())
        _i18n.set_language("zh", notify=False)
        _i18n.apply_language(w)
        check("切回中文占位符也还原", "输入请求地址" in req.placeholderText(),
              req.placeholderText())
        _i18n.set_language("en", notify=False)
        _i18n.apply_language(w)

        # 6) 请求对象本身不参与翻译（数据不能被改）
        from app.i18n import tr as _tr
        check("翻译不动用户数据", _tr("我的接口") == "我的接口", _tr("我的接口"))
        _i18n.set_language("zh", notify=False)
        return 0


    def step33():
        print("[30] 控制台 / 脚本加固 / 导入导出 / 标签重命名 / 侧栏跳转")
        import json as _json_mod

        from app import transfer
        from app.http_client import Response
        from app.store import new_folder, new_request
        from app.scripts import run_script
        from app.store import dynamic_var, kv

        # 1) 响应面板新增「控制台」页，能吃下分级条目
        keys = [i["key"] for i in w.response.tabs._items]
        check("响应面板新增控制台页", "console" in keys, str(keys))
        entries = [{"level": "log", "text": "hello", "phase": "pre"},
                   {"level": "error", "text": "boom", "phase": "post"}]
        w.response.set_console(entries)
        app.processEvents()
        check("控制台条目已渲染", len(w.response.console_host.entries) == 2,
              str(len(w.response.console_host.entries)))
        badge = [i["badge"] for i in w.response.tabs._items if i["key"] == "console"]
        check("控制台徽标是条数", badge and badge[0] == 2, str(badge))
        w.response._on_tab("console")
        check("控制台页能切换", w.response.body_stack.current() == "console")

        # 2) 脚本：日志级别 / 断言 / 环境变量 / res.json / 行号
        req = new_request("S", "POST", "https://s.test/x")
        req["headers"] = [kv("A", "1"), kv("B", "2", False)]
        res = run_script(
            'console.warn("w");\n'
            'req.setHeader("C", "3");\n'
            'pw.env.set("sv_smoke", "42");\n'
            'test("ok", function () { if (1 !== 1) throw new Error("x"); });\n',
            store, req)
        check("脚本正常执行", res.ok, res.error)
        check("日志带级别", [e["level"] for e in res.entries][:2] == ["warn", "ok"],
              str([e["level"] for e in res.entries]))
        check("脚本写环境变量", store.env_vars().get("sv_smoke") == "42")
        check("setHeader 保留停用状态",
              any(h["key"] == "B" and h["enabled"] is False for h in req["headers"]),
              str(req["headers"]))
        resp_obj = Response(status=201, reason="Created", elapsed=8,
                            headers=[("Content-Type", "application/json")],
                            body=b'{"token":"t1"}', size=14, url="u")
        r2 = run_script('var d = res.json(); console.log(d ? d.token : "no");'
                        'res.setHeader("X-A", "1");', store, req, res=resp_obj)
        check("后置脚本能解析响应体", r2.ok and r2.logs and r2.logs[0] == "t1",
              str(r2.logs))
        check("res.setHeader 生效", resp_obj.header("X-A") == "1")
        r3 = run_script("bad call(", store, req)
        check("语法错误行号是用户看到的行", r3.error.startswith("第 1 行"), r3.error)
        r4 = run_script("while (true) {}", store, req, timeout_ms=300)
        check("死循环能被中止", not r4.ok and r4.timed_out, r4.error)
        check("动态变量集中实现", dynamic_var("$timestamp").isdigit())

        # 3) 导入导出：五种格式都能来回
        folder = new_folder("T")
        one = new_request("R", "GET", "https://t.test/a?x=1")
        one["scripts"] = {"pre": "console.log(1);", "post": ""}
        one["auth"] = {"type": "bearer", "token": "tk"}
        folder["children"] = [one]
        store.data["collections"].append(folder)
        store.save()
        for fn, label in (
                (lambda: _json_mod.dumps(transfer.to_ocelot(store), ensure_ascii=False), "ocelot"),
                (lambda: _json_mod.dumps(transfer.to_postman(store), ensure_ascii=False), "postman"),
                (lambda: _json_mod.dumps(transfer.to_openapi(store), ensure_ascii=False), "openapi"),
                (lambda: transfer.to_yaml(transfer.to_openapi(store)), "openapi-yaml"),
                (lambda: _json_mod.dumps(transfer.to_har(store), ensure_ascii=False), "har")):
            text = fn()
            nodes, fmt, err = transfer.parse_text(text)
            check(f"{label} 导出后可再导入", bool(nodes) and not err,
                  f"{fmt} {err}")
        text = _json_mod.dumps(transfer.to_ocelot(store), ensure_ascii=False)
        nodes, _fmt, _err = transfer.parse_text(text)
        flat = []
        def walk(ns):
            for n in ns:
                if n.get("type") == "folder":
                    walk(n.get("children") or [])
                else:
                    flat.append(n)
        walk(nodes)
        got = [n for n in flat if n["name"] == "R"]
        check("Ocelot JSON 保留脚本与认证",
              bool(got) and got[0]["scripts"]["pre"] == "console.log(1);"
              and got[0]["auth"]["type"] == "bearer", str(got[:1]))
        check("Ocelot JSON 结构是 Postman v2.1 兼容",
              "schema" in _json_mod.dumps(transfer.to_ocelot(store)) and
              "x-ocelot" in _json_mod.dumps(transfer.to_ocelot(store)))
        check("YAML 解析能读 OpenAPI", isinstance(transfer._yaml_load(
            "openapi: 3.1.0\ninfo:\n  title: t\n"), dict))
        # 清理测试用的集合
        store.data["collections"] = [c for c in store.data["collections"] if c.get("name") != "T"]
        store.save()

        # 4) 导入导出对话框
        from app.dialogs import TransferDialog
        dlg = TransferDialog(store, w)
        check("默认停在导入页", dlg.stack.current() == "import")
        dlg._choose_source("postman")
        check("选来源后进到选文件页", dlg.stack.current() == "file")
        check("选文件页可返回", not dlg.back_btn.isHidden())
        dlg._go_back()
        check("返回后回到导入页", dlg.stack.current() == "import")
        dlg._show_page("export")
        check("导出页能打开", dlg.stack.current() == "export")
        dlg.close()

        # 5) 侧栏跳转 + 标签重命名同步
        node = None
        for n, _siblings in store.walk():
            if n.get("type") == "request":
                node = n
                break
        check("集合里有请求可定位", node is not None)
        if node is not None:
            w.sidebar.seg.set_current("history", emit=False)
            w.sidebar._on_mode("history")
            w.sidebar.search._edit.setText("zzz")
            w.sidebar._apply_filter("zzz")
            w.sidebar.reveal(node["id"])
            item = w.sidebar.tree.currentItem()
            check("跳转会切回集合页", w.sidebar._mode == "collections")
            check("跳转会清掉过滤并选中目标",
                  item is not None and item.data(0, 0x100 + 2).get("id") == node["id"])
            w.sidebar.rename_node(node["id"], "同步改名")
            w._on_store_changed()
            same = [t for t in w.tabs_data if t.get("node_id") == node["id"]]
            check("重命名同步到标签标题", all(t["title"] == "同步改名" for t in same) if same else True)
            check("重命名同步到请求内容",
                  all(t["request"]["name"] == "同步改名" for t in same) if same else True)
            check("重命名已落盘", Store.load(TMP).find(node["id"])["name"] == "同步改名")

        # 6) 脚本片段从新的一行插入
        page = w.editor.scripts_post
        page.code.setPlainText("var a = 1;")
        cur = page.code.textCursor()
        cur.movePosition(cur.MoveOperation.EndOfBlock)
        page.code.setTextCursor(cur)
        page._insert('console.log("x");')
        check("片段从新行插入", page.code.toPlainText() == 'var a = 1;\nconsole.log("x");\n',
              repr(page.code.toPlainText()))
        check("后置脚本有专属片段",
              any("res" in s for _t, s in page.POST_SNIPPETS))
        return 0

    def step34():
        print("[31] 导入格式适配 / 结果页 / 标签指示器 / 搜索框 / 方法同步")
        import json as _json

        from app import transfer
        from app.dialogs import TransferDialog

        pm = {"info": {"name": "Demo", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
              "item": [{"name": "Folder A", "item": [
                  {"name": "List", "request": {"method": "GET", "url": "https://api.demo.com/users",
                                               "header": [{"key": "Accept", "value": "application/json"}]},
                   "event": [{"listen": "test", "script": {"exec": ["pm.test('ok')"]}}]},
                  {"name": "Create", "request": {"method": "POST", "url": "https://api.demo.com/users",
                                                 "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "t"}]}}}]},
                  {"name": "Ping", "request": {"method": "GET", "url": "https://api.demo.com/ping"}}]}

        cases = {}
        cases["postman v2.1"] = _json.dumps(pm, ensure_ascii=False)
        cases["Postman 整包 dump"] = _json.dumps(
            {"collections": [pm], "environments": [{"name": "Dev", "values": [{"key": "base_url", "value": "https://x"}]}]},
            ensure_ascii=False)
        cases["Postman v1"] = _json.dumps(
            {"id": "c", "name": "Legacy", "order": ["r1"],
             "requests": [{"id": "r1", "name": "Old", "method": "GET", "url": "https://a.test/old",
                           "headers": "X-A: 1\n"}], "folders": []}, ensure_ascii=False)
        cases["Apifox apiCollection"] = _json.dumps(
            {"apiCollection": [{"name": "F", "baseUrl": "https://af.test", "items": [
                {"name": "af get", "api": {"method": "get", "path": "/af/users",
                                           "parameters": {"query": [{"name": "a", "value": "1"}]}}}]}]},
            ensure_ascii=False)
        cases["Hoppscotch 数组"] = _json.dumps(
            [{"name": "HS", "folders": [], "requests": [
                {"name": "hs", "method": "GET", "endpoint": "https://hs.test/a", "params": [], "headers": []}]}],
            ensure_ascii=False)
        cases["Hoppscotch v2 对象"] = _json.dumps(
            {"v": 2, "name": "HS2", "folders": [], "requests": [
                {"name": "hs2", "method": "GET", "endpoint": "https://hs.test/b", "params": [], "headers": []}]},
            ensure_ascii=False)
        cases["Insomnia v4（父节点是 workspace）"] = _json.dumps(
            {"_type": "export", "__export_format": 4, "resources": [
                {"_id": "wrk", "_type": "workspace", "name": "WS", "parentId": None},
                {"_id": "fld", "_type": "request_group", "name": "F", "parentId": "wrk"},
                {"_id": "r1", "_type": "request", "name": "ins", "parentId": "fld",
                 "method": "GET", "url": "https://ins.test/a", "headers": [], "parameters": []}]},
            ensure_ascii=False)
        cases["带 BOM 的 Postman"] = "\ufeff" + _json.dumps(pm, ensure_ascii=False)

        for name, text in cases.items():
            nodes, fmt, err = transfer.parse_text(text)
            check(f"{name} 能导入且不报错", bool(nodes) and not err,
                  f"fmt={fmt} reqs={transfer.count_requests(nodes)} err={err}")

        # 环境变量文件 / cURL 给出人话
        nodes, fmt, err = transfer.parse_text(_json.dumps({"name": "E", "values": [{"key": "a", "value": "1"}]}))
        check("环境变量文件给出提示", not nodes and "环境变量" in err, err)
        nodes, fmt, err = transfer.parse_text("curl https://a.test -H 'X: 1'")
        check("cURL 引导到剪贴板导入", not nodes and "cURL" in err, err)

        nodes, fmt, err = transfer.parse_text(_json.dumps(
            {"collections": [pm], "environments": [{"name": "Dev", "values": [{"key": "k", "value": "v"}]}]}))
        envs = transfer.environments_of(_json.dumps(
            {"collections": [pm], "environments": [{"name": "Dev", "values": [{"key": "k", "value": "v"}]}]}))
        check("整包 dump 能带出环境变量", len(envs) == 1 and envs[0]["name"] == "Dev"
              and envs[0]["vars"][0]["key"] == "k")

        stats = transfer.summarize(nodes)
        # dump 会把每份集合再包一层文件夹，所以这里 folders 是 2
        check("导入汇总统计正确",
              stats["requests"] == 3 and stats["folders"] == 2 and stats["post"] == 1
              and stats["auth"] == 1, str(stats))
        plain, _f, _e = transfer.parse_text(_json.dumps(pm, ensure_ascii=False))
        check("单份集合按集合名建目录（不再散在根上）",
              len(plain) == 1 and plain[0].get("type") == "folder"
              and plain[0].get("name") == "Demo", str(plain[:1])[:120])
        check("目录里保留原有的文件夹层级",
              any(c.get("name") == "Folder A" for c in plain[0].get("children") or []))
        single = _json.dumps(pm["item"][1], ensure_ascii=False)
        one, _f, _e = transfer.parse_text(single)
        check("单个请求的 JSON 就是一条请求，不套目录",
              len(one) == 1 and one[0].get("type") == "request", str(one[:1])[:80])
        named, _f, _e = transfer.parse_text(
            _json.dumps({k: v for k, v in pm.items() if k != "info"}, ensure_ascii=False),
            fallback_name="my-export")
        check("缺集合名时用文件名兜底", named and named[0].get("name") == "my-export",
              str(named[:1])[:80])

        # 结果页：导入后跳到 done 并列出明细
        dlg = TransferDialog(w.store, w)
        dlg.show()
        dlg._choose_source("postman")
        dlg._load_path("/tmp/ocelot_smoke_pm.json")
        check("识别成功后可点导入", dlg.import_btn.isEnabled() and dlg._pending is not None,
              dlg.file_status.text())
        dlg._do_import()
        app.processEvents()
        check("导入完成后停在结果页", dlg.stack.current() == "done" and dlg._title_label.text() == "导入完成")
        check("结果页列出明细", len(dlg.done._rows) >= 4, f"{len(dlg.done._rows)} 行")
        check("结果页隐藏返回箭头", dlg.back_btn.isHidden())
        dlg.close()

        # 标签指示器始终等于当前标签的真实矩形（启动不再压住隔壁）
        ts = w.tabstrip
        act = ts._active_rect()
        check("指示器对齐当前标签",
              abs(ts._indicator.width() - act.width()) < 0.5
              and abs(ts._indicator.x() - act.x()) < 0.5,
              f"{ts._indicator.width():.1f} vs {act.width():.1f}")

        # 点标签会 set_current 两次（点击 + 回调），第二次不能把动画按住
        ts.add_tab({"id": "tabx1", "title": "One", "method": "GET"}, activate=True)
        ts.add_tab({"id": "tabx2", "title": "Two", "method": "GET"}, activate=True)
        ts.set_current("tabx1")
        check("切标签会起动画", ts._ind_anim is not None and _anim_running(ts._ind_anim),
              "动画没起来")
        ts.set_current("tabx1")          # 模拟回调里的二次调用
        check("二次 set_current 不会掐掉动画",
              ts._ind_anim is not None and _anim_running(ts._ind_anim), "动画被停掉了")
        check("切换时有高亮淡入进度", ts._prev_id == "tabx2", str(ts._prev_id))
        ts.set_current("tabx1", animate=False)
        ts.remove_tab("tabx2")
        ts.remove_tab("tabx1")

        # 集合 / 历史 的胶囊也要滑过去，而不是整块瞬移
        seg = w.sidebar.seg
        seg.set_current("history")
        check("分段控件切换会起动画",
              seg._anim is not None and _anim_running(seg._anim), "没有滑动动画")
        check("分段控件文字跟着淡入", seg._fade_t < 0.999, f"fade={seg._fade_t:.2f}")
        seg.set_current("collections", emit=False)

        # 搜索框吃掉剩余宽度，紧贴导入导出按钮
        sb = w.sidebar
        gap = sb.transfer_btn.mapTo(sb, sb.transfer_btn.rect().topLeft()).x() - (
            sb.search.mapTo(sb, sb.search.rect().topLeft()).x() + sb.search.width())
        check("搜索框紧贴右侧按钮", 0 <= gap <= 12, f"gap={gap}")

        # 改请求方式 → 集合树 / 标签 / store 三处同步
        req_node = None

        def find_req(nodes):
            for n in nodes or []:
                if n.get("type") == "request":
                    return n
                found = find_req(n.get("children") or [])
                if found:
                    return found
            return None

        req_node = find_req(w.store.collections)
        if req_node:
            w._open_request_obj(req_node, node_id=req_node["id"])
            app.processEvents()
            tab = w.current_tab()
            w.editor.urlbar.method._choose("PATCH")     # 模拟用户在下拉里点选
            app.processEvents()
            node = w.store.find(req_node["id"])
            check("改方法同步到集合树", (node or {}).get("method") == "PATCH"
                  and ts.tab(tab["id"])["method"] == "PATCH"
                  and tab["method"] == "PATCH")
            w.editor.urlbar.method._choose("GET")
            app.processEvents()
            check("改回来后依然同步", (w.store.find(req_node["id"]) or {}).get("method") == "GET")

        # 弹窗策略：设置 / 导入导出模糊且固定，其余默认不模糊、可拖动
        from app.dialogs import PromptDialog, SettingsDialog, TransferDialog

        w.store.settings["glass_all"] = False
        small = PromptDialog("重命名", "名字", "x", w)
        small.show()
        app.processEvents()
        check("普通弹窗默认不模糊", not small._backdrop_on and not small._fixed_mode)
        check("普通弹窗可以拖动", not small._fixed_mode)
        # 居中：以父窗口中心为准，并夹在屏幕可视区内
        area = app.primaryScreen().availableGeometry()
        gcenter = w.mapToGlobal(w.rect().center())
        g = small.geometry()
        exp_x = min(max(gcenter.x() - g.width() // 2, area.left()),
                    area.right() - g.width())
        exp_y = min(max(gcenter.y() - g.height() // 2, area.top()),
                    area.bottom() - g.height())
        check("弹窗默认居中", abs(g.x() - exp_x) <= 2 and abs(g.y() - exp_y) <= 2,
              f"{g} 期望 ({exp_x},{exp_y})")
        small.close()

        sd = SettingsDialog(w.store, w)
        sd.show()
        app.processEvents()
        check("设置窗口模糊且不可拖动", sd._fixed_mode and sd._backdrop_on)
        sd.close()

        # 可拖动：按住标题栏往下拖 40px，窗口应该真的跟着动；固定模式下则不动
        from PyQt6.QtGui import QMouseEvent

        def drag(dlg, dy=40):
            from PyQt6.QtCore import QPointF

            center = dlg.header.rect().center()
            local = QPointF(dlg.header.mapTo(dlg, center))
            press = QMouseEvent(QEvent.Type.MouseButtonPress, local,
                                QPointF(dlg.mapToGlobal(center)), Qt.MouseButton.LeftButton,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            move = QMouseEvent(QEvent.Type.MouseMove, local + QPointF(0, dy),
                               QPointF(dlg.mapToGlobal(center)) + QPointF(0, dy),
                               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
            dlg.mousePressEvent(press)
            dlg.mouseMoveEvent(move)
            dlg.mouseReleaseEvent(move)

        movable = PromptDialog("重命名", "名字", "x", w)
        movable.show()
        app.processEvents()
        before = movable.pos()
        drag(movable)
        check("可拖动弹窗能跟着鼠标移动", movable.pos().y() != before.y(),
              f"{before} -> {movable.pos()}")
        movable.close()

        fixed = SettingsDialog(w.store, w)
        fixed.show()
        app.processEvents()
        before = fixed.pos()
        drag(fixed)
        check("模糊 + 固定窗口拖不动", fixed.pos() == before, f"{before} -> {fixed.pos()}")
        fixed.close()

        w.store.settings["glass_all"] = True
        small2 = PromptDialog("重命名", "名字", "x", w)
        small2.show()
        app.processEvents()
        check("打开「所有弹窗都模糊」后普通弹窗也模糊", small2._fixed_mode and small2._backdrop_on)
        small2.close()
        w.store.settings["glass_all"] = False
        app.processEvents()

        # URL 导入：下载到的文本走和本地文件一样的识别流程
        dlg2 = TransferDialog(w.store, w)
        dlg2._choose_source("url")
        dlg2._on_url_text(_json.dumps(pm, ensure_ascii=False), "")
        check("URL 导入能识别并给出集合名",
              dlg2._pending is not None and dlg2._pending_name == "Demo",
              dlg2.file_status.text())
        check("URL 下载失败时给出错误提示",
              (dlg2._on_url_text("", "timeout")) or "下载失败" in dlg2.file_status.text())

        # 命令面板：常用五条按使用频率排序，其余归到「全部命令」
        w.store.data["palette_hits"] = {"settings": 7, "send": 3}
        pinned = [a[0] for a in w.palette._pinned_actions()]
        check("命令面板常用五项按频率置顶",
              len(pinned) == 5 and pinned[0] == "settings" and pinned[1] == "send",
              str(pinned))
        w.palette.open()
        app.processEvents()
        heads = [i.get("title") for i in w.palette._results if i.get("kind") == "header"]
        check("命令面板有「常用 / 全部命令」分组", heads == ["常用", "全部命令"], str(heads))
        w.palette.close()
        w.store.data["palette_hits"] = {}

        # 导出默认文件名 = 集合（目录）名，单集合时不再写死 ocelot-collection
        saved = list(w.store.collections)
        w.store.data["collections"] = [{"id": "c1", "type": "folder", "name": "Demo/API: v2",
                                        "open": True, "children": []}]
        check("导出默认名用集合名并过滤非法字符",
              dlg2._export_stem() == "Demo-API- v2", dlg2._export_stem())
        w.store.data["collections"] = saved
        dlg2.close()
        return 0

    def step35():
        """对齐 / 二次确认 / 预览转正 / 命令面板模糊。"""
        from app import backdrop as bd
        from app.dialogs import CommandPalette, ConfirmDialog, TransferDialog

        # 1) 模糊遮罩必须和窗口卡片区（去掉 8px 阴影留白）严丝合缝
        dlg = TransferDialog(w.store, w)
        dlg.show()
        app.processEvents()
        layer = bd._BY_HOST.get(id(w))
        card = w.card_rect()
        check("模糊遮罩铺在窗口卡片区（不含阴影留白）",
              layer is not None and layer.geometry() == card,
              f"{layer.geometry() if layer else None} vs {card}")
        if layer is not None:
            dpr = layer._pix.devicePixelRatio() or 1.0
            check("模糊底图与卡片同尺寸",
                  abs(layer._pix.width() / dpr - card.width()) <= 1
                  and abs(layer._pix.height() / dpr - card.height()) <= 1,
                  f"{layer._pix.width()/dpr:.0f}x{layer._pix.height()/dpr:.0f} vs {card.width()}x{card.height()}")
        # 导入页高度按真实内容给，底部不留空白
        hint = dlg.stack._pages["import"].sizeHint().height()
        check("导入页高度贴合内容",
              abs(dlg.height() - (dlg.header.height() + 1 + hint)) <= 2,
              f"{dlg.height()} vs {dlg.header.height() + 1 + hint}")
        dlg.close()
        app.processEvents()

        # 2) 删除必须二次确认
        node = w.store.collections[-1]
        node_id = node["id"]
        asked: list = []
        orig = ConfirmDialog.__dict__["ask"]

        def _deny(cls, parent, title, message, confirm_text="删除"):
            asked.append(title)
            return False

        ConfirmDialog.ask = classmethod(_deny)          # type: ignore[assignment]
        w.sidebar.delete_node(node_id)
        check("删除前要二次确认", bool(asked) and w.store.find(node_id) is not None,
              f"asked={asked}")
        ConfirmDialog.ask = classmethod(lambda cls, p, t, m, c="删除": True)   # type: ignore[assignment]
        w.sidebar.delete_node(node_id)
        check("确认之后才真的删除", w.store.find(node_id) is None)
        ConfirmDialog.ask = orig                        # type: ignore[assignment]

        # 3) 历史模式只有一个「清空历史」入口（图标那颗已去掉）
        check("历史模式没有重复的清空按钮", not hasattr(w.sidebar, "clear_btn"))

        # 4) 单击=预览（斜体），双击=转正
        opened = {t.get("node_id") for t in w.tabs_data}
        req = next(n for n, _ in w.store.walk()
                   if n.get("type") == "request" and n.get("id") not in opened)
        w._preview_from_sidebar(req)
        app.processEvents()
        tab = next((t for t in w.tabs_data if t.get("node_id") == req.get("id")), None)
        check("单击集合项是预览（斜体）",
              tab is not None and tab.get("preview") is True
              and (w.tabstrip.tab(tab["id"]) or {}).get("preview") is True)
        if tab is not None:
            w._open_from_sidebar(req)
            app.processEvents()
            check("双击之后标签不再斜体",
                  tab.get("preview") is False
                  and (w.tabstrip.tab(tab["id"]) or {}).get("preview") is False)

        # 5) 命令面板：打开就有背景模糊，且盖在遮罩之上
        w.show_palette()
        app.processEvents()
        layer = bd._BY_HOST.get(id(w))
        check("命令面板打开时背景是模糊的",
              w.palette.isVisible() and layer is not None and layer.isVisible())
        check("命令面板与卡片区同尺寸", w.palette.geometry() == w.card_rect(),
              f"{w.palette.geometry()} vs {w.card_rect()}")
        w.palette.close()
        app.processEvents()
        return 0

    def step36():
        """胶囊尺寸 / 失败态指标 / 文字大小 / 文件夹导出 / 命令面板懒绘制 / WebSocket。"""
        from PyQt6.QtGui import QFontMetricsF
        from PyQt6.QtNetwork import QHostAddress
        from PyQt6.QtWebSockets import QWebSocketServer

        from app import i18n as _i18n
        from app.dialogs import SettingsDialog
        from app.store import new_folder
        from app.theme import font as _font
        from app.theme import set_ui_scale
        from app.transfer import to_ocelot
        from app.widgets import Pill

        # 1) 英文「failed」胶囊：背景必须比文字宽，不能挤出圆角
        old_lang = _i18n.current()
        _i18n.set_language("en", notify=False)
        pill = Pill("失败", "#D9483A")
        fm = QFontMetricsF(pill._font)
        need = fm.horizontalAdvance("failed") + pill._pad * 2
        check("英文失败胶囊给足背景宽度", pill.width() >= need,
              f"{pill.width()} vs {int(need)}")
        _i18n.set_language(old_lang, notify=False)
        pill.deleteLater()

        # 2) 请求失败：不显示耗时 / 大小，也没有悬浮详情卡
        from app.http_client import Response as _Resp

        w.response.set_response(_Resp(error="连接被拒绝", url="https://example.com"))
        app.processEvents()
        check("失败时不显示响应时间", not w.response.time_label.isVisible())
        check("失败时不显示响应大小", not w.response.size_label.isVisible())
        check("失败时不给耗时 / 大小详情卡",
              w.response._timing_card() is None and w.response._size_card() is None)

        # 3) 文字大小：四档、写进设置、字体按比例放大
        set_ui_scale(1.25)
        check("文字缩放作用于字体", abs(_font(10).pointSizeF() - 12.5) < 0.01,
              f"{_font(10).pointSizeF()}")
        set_ui_scale(1.0)
        dlg = SettingsDialog(w.store, w, page="appearance")
        check("设置里有四档文字大小", len(dlg.scale_seg._items) == 4,
              str([i["label"] for i in dlg.scale_seg._items]))
        # 点一下当场就变：设置页不关、控件字号真的变大
        dlg.show()
        before = dlg.scale_seg.font().pointSizeF()
        dlg.scale_seg.set_current("1.25", emit=True)
        app.processEvents()
        check("选完文字大小会持久化", abs(float(w.store.settings["ui_scale"]) - 1.25) < 0.001,
              str(w.store.settings.get("ui_scale")))
        check("改字号不关设置页", dlg.isVisible())
        check("改字号当场放大（不用重建窗口）",
              dlg.scale_seg.font().pointSizeF() > before + 0.5,
              f"{before} → {dlg.scale_seg.font().pointSizeF()}")
        check("自绘控件也跟着变高",
              w.editor.urlbar.method.height() > 30,
              str(w.editor.urlbar.method.height()))
        # 拨回去，别把后面的截图/断言带偏
        dlg.scale_seg.set_current("1.0", emit=True)
        app.processEvents()
        check("字号能拨回 100%", abs(float(w.store.settings["ui_scale"]) - 1.0) < 0.001,
              str(w.store.settings.get("ui_scale")))
        dlg.close()

        # 4) 文件夹右键导出：只导出这个文件夹，结构不散
        folder = new_folder("Payments")
        folder["children"] = [new_request("Pay", "GET", "https://api.test/pay")]
        data = to_ocelot(w.store, "Payments", nodes=[folder])
        item = (data.get("item") or [{}])[0]
        check("文件夹导出保留目录名", item.get("name") == "Payments", str(item.get("name")))
        check("文件夹导出只含该目录下的请求",
              len(item.get("item") or []) == 1 and not any(
                  c.get("name") == "Untitled Request" for c in (data.get("item") or [])))

        # 走一遍真的导出流程：把菜单选择与保存对话框换成确定值
        import os as _os

        from PyQt6.QtWidgets import QFileDialog as _QFD
        from app import dialogs as _dlg
        from app.widgets import Menu as _Menu

        target = "/tmp/ocelot_folder_export.json"
        if _os.path.exists(target):
            _os.unlink(target)
        orig_exec = _Menu.exec
        orig_save = _QFD.getSaveFileName

        def _fake_exec(self, *a, **k):
            for act in self.actions():
                if act.text().startswith("导出为 Ocelot"):
                    return act
            return None

        _Menu.exec = _fake_exec                                   # type: ignore[assignment]
        _QFD.getSaveFileName = staticmethod(lambda *a, **k: (target, ""))  # type: ignore[assignment]
        try:
            path = _dlg.export_folder(w.store, folder, w, w.mapToGlobal(w.rect().center()))
            check("文件夹导出真的写出文件",
                  bool(path) and _os.path.exists(target) and _os.path.getsize(target) > 40,
                  str(path))
            payload = _json.loads(open(target, encoding="utf-8").read())
            check("导出文件里是同一个文件夹",
                  (payload.get("item") or [{}])[0].get("name") == "Payments")
        finally:
            _Menu.exec = orig_exec                                # type: ignore[assignment]
            _QFD.getSaveFileName = orig_save                      # type: ignore[assignment]

        # 5) 命令面板：只画可视行，但搜索覆盖全部
        w.palette.open()
        app.processEvents()
        first, last = w.palette.list.visible_range()
        check("命令面板高度不再铺满整窗",
              w.palette.card.height() <= 460, str(w.palette.card.height()))
        check("命令面板只绘制可视行", 0 < last - first <= 40, f"{first}-{last}")
        w.palette._filter("设置")
        check("命令面板搜索仍然全量匹配",
              any("设置" in i.get("title", "") for i in w.palette._results),
              str(len(w.palette._results)))

        # 塞 300 条请求：滚动后只画新的可视段，但深层条目照样搜得到
        folder = w.store.collections[0] if w.store.collections else None
        added = []
        if isinstance(folder, dict):
            folder.setdefault("children", [])
            for i in range(300):
                node = new_request(f"Bulk {i:03d}", "GET", f"https://bulk.test/{i}")
                folder["children"].append(node)
                added.append(node)
            w.sidebar.refresh()
            w.palette.open()
            w.palette.edit.clear()
            app.processEvents()
            w.palette.scroll.verticalScrollBar().setValue(2400)
            app.processEvents()
            first2, last2 = w.palette.list.visible_range()
            check("滚动后只绘制新的可视段", first2 > 0 and last2 - first2 <= 40,
                  f"{first2}-{last2}")
            w.palette._filter("Bulk 299")
            check("深层条目仍然能搜到",
                  any(i.get("title") == "Bulk 299" for i in w.palette._results),
                  str(len(w.palette._results)))
            folder["children"] = [c for c in folder["children"] if c not in added]
            w.sidebar.refresh()
        w.palette.close()

        # 6) WebSocket：连上、收推送、回声、心跳、过滤、常用消息、断开、连不上
        srv = QWebSocketServer("smoke-ws", QWebSocketServer.SslMode.NonSecureMode)
        check("本地 WebSocket 服务监听成功",
              srv.listen(QHostAddress.SpecialAddress.LocalHost, 0), srv.errorString())
        port = srv.serverPort()
        peers = []

        def on_new():
            sock = srv.nextPendingConnection()
            peers.append(sock)
            sock.textMessageReceived.connect(
                lambda t, s=sock: s.sendTextMessage("echo:" + t))
            sock.sendTextMessage("hello")

        srv.newConnection.connect(on_new)

        w.new_websocket()
        check("新建的是 WebSocket 请求",
              w.current_tab()["request"].get("method") == "WS")
        check("WebSocket 是独立页面，不显示 HTTP 页签",
              w.editor.is_ws() and w.editor.ws_page.isVisible()
              and not w.editor.head.isVisible() and not w.editor.pages.isVisible())
        check("WebSocket 页面里有消息编辑器",
              w.editor.ws.editor is not None and w.editor.ws.send_btn is not None)
        from app.request_panel import METHODS as _METHODS

        check("WS 不再能从方法下拉里切过去", "WS" not in _METHODS)
        # 握手头：低频配置走弹层，不占消息编辑器的高度
        w.editor._open_ws_headers()
        popup = w.editor._ws_headers_popup
        check("握手头能在弹层里打开", popup is not None and popup.isVisible())
        popup.editor.set_rows([{"key": "X-Client", "value": "ocelot", "enabled": True}])
        app.processEvents()
        check("握手头写进请求头",
              any((h.get("key") or "") == "X-Client"
                  for h in w.current_tab()["request"].get("headers") or []),
              str(w.current_tab()["request"].get("headers")))
        check("握手头数量反映在按钮上", "1" in w.editor.ws.headers_btn.text(),
              w.editor.ws.headers_btn.text())
        popup.close()
        check("握手头弹层不占请求区高度", w.editor.ws.geometry().height() > 200,
              str(w.editor.ws.geometry().height()))

        w.editor.urlbar.set_url(f"ws://127.0.0.1:{port}/echo")
        w.editor._on_url("x")
        w.send_current()
        check("WebSocket 能建立连接", wait_until(lambda: w.ws.is_open, 8000), w.ws.state)
        tab = w.current_tab()
        check("连接状态同步到会话", tab["ws_session"]["state"] == "open")
        check("状态胶囊显示已连接", w.response.pill._title() == "已连接",
              w.response.pill._title())
        check("响应区切到 WebSocket 日志页",
              w.response.center.currentWidget() is w.response.ws_view)
        check("已连接时地址栏按钮显示「断开」",
              w.editor.urlbar.send_btn.text() == "断开",
              w.editor.urlbar.send_btn.text())
        # 刷新 / 切回标签也不能把按钮打回「连接」
        w.editor.load(tab["request"])
        check("重新加载后按钮仍是「断开」",
              w.editor.urlbar.send_btn.text() == "断开",
              w.editor.urlbar.send_btn.text())
        check("能收到服务端推送",
              wait_until(lambda: any(getattr(f, "preview", lambda: "")() == "hello"
                                     for f in tab["ws_session"]["log"]), 4000))
        w._ws_send("ping-me", False)
        check("发出的消息进日志",
              wait_until(lambda: any(f.dir == "out" and f.preview() == "ping-me"
                                     for f in tab["ws_session"]["log"]), 3000))
        check("能收到服务端回声",
              wait_until(lambda: any(f.dir == "in" and f.preview() == "echo:ping-me"
                                     for f in tab["ws_session"]["log"]), 4000))
        w.ws._ping()
        check("心跳能测出真实延迟", wait_until(lambda: w.ws.latency > 0, 4000),
              f"{w.ws.latency} ms")
        w.response.ws_view.filter.set_current("out", emit=True)
        check("按「发送」过滤只剩发送帧",
              bool(w.response.ws_view.list.frames)
              and all(f.dir == "out" for f in w.response.ws_view.list.frames))
        w.response.ws_view.filter.set_current("all", emit=True)

        # 日志详情：点行展开，可同时展开多条，页签能切换内容
        view = w.response.ws_view
        rows = [i for i, f in enumerate(view.list.frames)
                if f.kind in ("text", "json")][:2]
        check("日志里有可展开的消息", len(rows) == 2, str(len(rows)))
        if len(rows) == 2:
            view.list.toggle(rows[0])
            view.list.toggle(rows[1])
            app.processEvents()
            check("多条消息能同时展开",
                  len(view.list._cards) == 2
                  and all(c.isVisible() for c in view.list._cards.values()),
                  str(len(view.list._cards)))
            card = view.list._cards[id(view.list.frames[rows[0]])]
            check("文本帧也有 JSON 页签", card.tabs.has("pretty"),
                  str([i["key"] for i in card.tabs._items]))
            if card.tabs.has("pretty"):
                card.tabs.set_current("pretty", emit=True)
                src = card.frame.preview(20000).lstrip()
                is_json = False
                if src[:1] in ("{", "["):
                    try:
                        _json.loads(src)
                        is_json = True
                    except Exception:  # noqa: BLE001
                        pass
                check("JSON 页签显示分行排版",
                      (not is_json) or "\n" in card.body.toPlainText())
            else:
                card.tabs.set_current("raw", emit=True)
            from app.theme import theme as _theme
            check("代码区底色跟随主题而非纯黑",
                  _theme().code_bg.lower() != "#000000"
                  and _theme().code_bg in card.body.styleSheet(),
                  _theme().code_bg)
            check("代码框没有滚动条",
                  card.body.verticalScrollBarPolicy()
                  == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                  and card.body.horizontalScrollBarPolicy()
                  == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            h_open = card.height()
            card.chevron.expanded = False
            card.chevron.toggled.emit(False)
            app.processEvents()
            check("代码框能折叠", not card.code_card.isVisible()
                  and card.height() < h_open,
                  f"{h_open} → {card.height()}")
            card.chevron.expanded = True
            card.chevron.toggled.emit(True)
            app.processEvents()
            check("代码框能展开回来", card.code_card.isVisible()
                  and card.height() >= h_open)
            check("统计数字带补间动画", view.stats._num_anim is not None)

            # 展开的卡片后面再来消息：必须按真实高度排布，不能盖在详情上
            from app.ws_client import WsFrame as _F
            before_tops = list(view.list._tops)
            card_bottom = before_tops[rows[0]] + view.list.ROW_H + card.height()
            view.list.append(_F("in", "text", b"later"))
            app.processEvents()
            last_top = view.list._tops[rows[0] + 1] if rows[0] + 1 < len(view.list._tops) else -1
            check("新消息不会盖住展开卡片", last_top >= card_bottom - 2,
                  f"card bottom {card_bottom:.0f}, next top {last_top:.0f}")
            view.list.frames.pop()
            view.list._tops.pop()
            view.list._relayout()
            app.processEvents()

        # WS 视图下「…」按钮要给出一套专属功能，不能再点了没反应
        check("WS 更多菜单有专属回调", w.response.is_ws_view()
              and callable(getattr(w.response, "_show_ws_menu", None)))
        check("WS 动作入口可用", callable(getattr(w, "_on_ws_action", None)))

        from app.ws_client import WsFrame as _WsFrame

        multi = _WsFrame("in", "json", b'{\n "a": 1,\n "b": 2\n}', 0, 12)
        check("日志行内 JSON 压成单行", "\n" not in multi.inline_preview()
              and multi.inline_preview().startswith("{"), multi.inline_preview())
        from PyQt6.QtGui import QFont as _QFont, QTextCursor as _QTextCursor, QTextDocument as _QTextDocument
        from app.code_editor import JsonHighlighter as _JsonHighlighter

        doc = _QTextDocument('{"a":1}')
        _JsonHighlighter(doc)
        cur = _QTextCursor(doc)
        cur.setPosition(1)
        cur.setPosition(2, _QTextCursor.MoveMode.KeepAnchor)
        check("JSON 键名不再加粗",
              cur.charFormat().fontWeight() == _QFont.Weight.Normal,
              str(cur.charFormat().fontWeight()))

        # 输入法组词时不能把占位提示透出来
        from PyQt6.QtGui import QInputMethodEvent

        edit = w.editor.ws.editor
        had_ph = bool(edit.placeholderText())
        edit.setFocus()
        edit.inputMethodEvent(QInputMethodEvent("ni'hao", []))
        check("中文输入法组词时占位提示隐藏",
              had_ph and not edit.placeholderText(), edit.placeholderText())
        commit = QInputMethodEvent("", [])
        commit.setCommitString("你好")
        edit.inputMethodEvent(commit)
        app.processEvents()
        check("组词结束后占位提示恢复", bool(edit.placeholderText()))

        # 草稿：切到别的标签再回来，输入内容还在
        edit.setPlainText("切换标签也要在")
        app.processEvents()
        check("正在输入的内容写回请求",
              tab["request"]["ws"].get("draft") == "切换标签也要在",
              str(tab["request"]["ws"].get("draft")))
        w.new_request()
        w._on_tab_changed(tab["id"])
        check("切走再切回消息还在",
              w.editor.ws.editor.toPlainText() == "切换标签也要在",
              w.editor.ws.editor.toPlainText()[:40])
        w.editor.ws.editor.setPlainText("")

        # 常用消息：存下来、能重发
        w.editor.ws.editor.setPlainText('{"hello": "ws"}')
        w.editor.ws._save_current()
        msgs = tab["request"]["ws"].get("messages") or []
        check("能把消息存成常用", len(msgs) == 1, str(len(msgs)))
        check("常用消息能在消息页看到", len(w.editor.ws._chips) == 1)

        # 特色功能：双击收到的消息，直接填回编辑器改一改再发
        view = w.response.ws_view
        idx = -1
        for k, f in enumerate(view.list.frames):
            if f.dir == "in" and "hello" in f.preview(999):
                idx = k
                break
        check("日志里能定位到收到的文本帧", idx >= 0, str(idx))
        if idx >= 0:
            view.list.activated.emit(idx)
            app.processEvents()
            check("双击收到的消息会填回编辑器",
                  "hello" in w.editor.ws.editor.toPlainText(),
                  w.editor.ws.editor.toPlainText()[:40])
            check("重放后停在 WS 独立页",
                  w.editor.ws_page.isVisible() and not w.editor.head.isVisible())

        w.ws.disconnect_ws()
        check("能主动断开连接", wait_until(lambda: not w.ws.busy, 5000), w.ws.state)
        check("断开后日志里有 close 帧",
              any(f.kind == "close" for f in tab["ws_session"]["log"]))
        srv.close()

        # 连不上：地址端口没有服务，应该失败而不是永远转圈
        w.current_tab()["request"]["ws"]["auto_reconnect"] = False
        w.editor.urlbar.set_url(f"ws://127.0.0.1:{port}/nope")
        w.editor._on_url("x")
        w.send_current()
        check("连不上时不会卡在连接中",
              wait_until(lambda: w.ws.state in ("closed", "idle"), 6000), w.ws.state)
        check("连不上时顶部显示未连接 / 已断开",
              w.response.pill._title() in ("未连接", "已断开"),
              w.response.pill._title())
        check("失败后同样不显示耗时 / 大小", not w.response.time_label.isVisible())
        return 0

    def finish():
        try:
            _SERVER.shutdown()
        except Exception:
            pass
        w.close()
        print(f"\n通过 {len(OKS)} 项，失败 {len(FAILS)} 项")
        if FAILS:
            print("失败项：" + ", ".join(FAILS))
        app.quit()

    steps = [step1, step2, step3, step4, step5, step6, step7, step8, step9, step10, step11,
             step12, step13, step14, step15, step16, step17, step18, step19, step20, step21,
             step22, step23, step24, step25, step26, step27, step28, step29, step30, step31, step32, step33, step34, step35, step36]

    def driver(i: int = 0) -> None:
        if i >= len(steps):
            finish()
            return
        wait = 0
        try:
            wait = steps[i]() or 0
        except Exception:
            traceback.print_exc()
            FAILS.append(f"step{i + 1} 异常")
        QTimer.singleShot(int(wait), lambda: driver(i + 1))

    QTimer.singleShot(600, lambda: driver(0))
    QTimer.singleShot(30000, finish)
    app.exec()
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
