"""为 README 生成截图。

用法：python3 tools/readme_shots.py
输出：docs/shot-*.png

主界面、请求体、响应树、Mock 中心与日志、二维码、命令面板、云同步、接口文档、设置、浅色。
响应数据是本地造的，不依赖网络，多跑几次结果一致。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import store as store_mod  # noqa: E402
from app.main_window import MainWindow  # noqa: E402
from app.store import Store, new_folder, new_request, uid  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
SANDBOX = "/tmp/ocelot_readme_state"

USERS = json.dumps({
    "page": 2,
    "per_page": 3,
    "total": 128,
    "items": [
        {"id": 7, "login": "shaoao", "name": "Shao Ao", "role": "owner",
         "email": "shaoao@example.com", "two_factor": True, "joined": "2023-04-18"},
        {"id": 8, "login": "ada", "name": "Ada Lovelace", "role": "maintainer",
         "email": "ada@example.com", "two_factor": False, "joined": "2024-01-06"},
        {"id": 9, "login": "grace", "name": "Grace Hopper", "role": "developer",
         "email": "grace@example.com", "two_factor": True, "joined": "2024-09-22"},
    ],
}, ensure_ascii=False, indent=2).encode()

CREATED = json.dumps({
    "id": 10,
    "login": "ada",
    "name": "Ada Lovelace",
    "role": "maintainer",
    "email": "ada@example.com",
    "created_at": "2026-11-17 03:41:08",
}, ensure_ascii=False, indent=2).encode()

BODY_JSON = ('{\n'
             '  "name": "Ada Lovelace",\n'
             '  "role": "maintainer",\n'
             '  "email": "ada@example.com",\n'
             '  "tags": ["api", "client"]\n'
             '}')

GET_URL = "https://api.example.com/v1/users?page=2&per_page=3&sort=joined"


def demo_get():
    """截图用的请求：参数、请求头都填好，别让截图里全是占位符。"""
    req = new_request("用户列表", "GET", "https://api.example.com/v1/users")
    req["params"] = [
        {"key": "page", "value": "2", "enabled": True, "type": "number", "desc": "页码"},
        {"key": "per_page", "value": "3", "enabled": True, "type": "number", "desc": "每页条数"},
        {"key": "sort", "value": "joined", "enabled": True, "type": "text", "desc": "排序字段"},
        {"key": "archived", "value": "false", "enabled": False, "type": "bool", "desc": "含归档"},
    ]
    req["headers"] = [
        {"key": "Accept", "value": "application/json", "enabled": True, "desc": ""},
        {"key": "X-Trace", "value": "c1f0-4b2e-9d", "enabled": True, "desc": "排查用"},
    ]
    return req


def demo_post():
    req = new_request("创建用户", "POST", "https://api.example.com/v1/users")
    req["headers"] = [
        {"key": "Accept", "value": "application/json", "enabled": True, "desc": ""},
        {"key": "Content-Type", "value": "application/json", "enabled": True, "desc": ""},
    ]
    req["body"] = {"mode": "json", "raw": BODY_JSON, "form": [], "file": ""}
    return req


def demo_collections():
    """截图用的集合树：别把用户自己的请求名放进 README。"""
    users = new_folder("用户服务")
    users["children"] = [demo_get(), demo_post()]

    local = new_folder("本地 Mock")
    mock_user = new_request("用户信息（动态）", "GET", "http://127.0.0.1:8787/api/user")
    mock_vip = new_request("鉴权规则", "GET", "http://127.0.0.1:8787/api/profile")
    mock_vip["headers"] = [{"key": "token", "value": "123", "enabled": True, "desc": ""}]
    local["children"] = [mock_user, mock_vip]

    return [{"id": uid(), "type": "folder", "name": "我的接口", "open": True,
             "children": [users, local]}]


def isolate_state():
    """截图不碰真实会话：拷一份到临时目录再改。"""
    os.makedirs(SANDBOX, exist_ok=True)
    real = store_mod.STATE_FILE
    sandbox = os.path.join(SANDBOX, "state.json")
    if os.path.exists(real) and not os.path.exists(sandbox):
        shutil.copy(real, sandbox)
    if os.path.exists(sandbox):
        with open(sandbox, encoding="utf-8") as fh:
            data = json.load(fh)
        data["open_tabs"] = []
        data.setdefault("settings", {})["theme"] = "dark"
        data.setdefault("mock", {})["auto_start"] = False
        with open(sandbox, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    return sandbox


def main() -> int:
    os.makedirs(DOCS, exist_ok=True)
    state_path = isolate_state()

    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    store = Store.load(state_path)
    store.data["collections"] = demo_collections()
    store.data["history"] = []
    apply_theme(app, theme_by_name("dark"))
    w = MainWindow(store)
    w.resize(1360, 860)
    w.show()

    made = []

    def save(widget, name):
        path = os.path.join(DOCS, f"shot-{name}.png")
        widget.grab().save(path)
        made.append(path)

    def fake_response(body=USERS, status=200, url=GET_URL):
        from app.http_client import Response

        return Response(
            status=status, reason="OK" if status == 200 else "Created",
            headers=[("content-type", "application/json; charset=utf-8"),
                     ("content-length", str(len(body))),
                     ("server", "nginx/1.25.3"),
                     ("cache-control", "max-age=60"),
                     ("x-ratelimit-remaining", "57"),
                     ("date", "Tue, 17 Nov 2026 03:40:12 GMT")],
            body=body, elapsed=138, size=len(body), url=url,
            content_type="application/json; charset=utf-8",
            timing={"prepare": 3, "dns": 6, "tcp": 11, "ssl": 24, "ttfb": 88,
                    "download": 4, "process": 2})

    w._open_request_obj(demo_get(), node_id=None)
    get_tab = w.tabs_data[0]["id"]

    def switch_to(tab_id):
        w.tabstrip.set_current(tab_id, animate=False)
        w._on_tab_changed(tab_id)

    # ---- 1. 主界面：请求 + 响应
    def s_main(next_):
        w.response.set_response(fake_response())
        QTimer.singleShot(500, lambda: (save(w, "main"), next_()))

    # ---- 2. 请求体：JSON 编辑 + 校验
    def s_body(next_):
        w._open_request_obj(demo_post(), node_id=None)
        w.editor.tabs.set_current("body", emit=True)
        w.editor._on_tab("body")
        w.response.set_response(fake_response(body=CREATED, status=201,
                                              url="https://api.example.com/v1/users"))
        QTimer.singleShot(550, lambda: (save(w, "request"), next_()))

    # ---- 3. 响应：树形
    def s_tree(next_):
        switch_to(get_tab)
        w.editor.tabs.set_current("params", emit=True)
        w.editor._on_tab("params")
        w.response.set_response(fake_response())
        w.response.tabs.set_current("tree", emit=True)
        w.response._on_tab("tree")
        QTimer.singleShot(600, lambda: (save(w, "response"), next_()))

    # ---- 4. Mock 中心（先打几次，让命中次数与日志有内容）
    def s_mock(next_):
        from app.mock_panel import MockDialog
        from app.mock_server import default_routes

        from app.mock_server import mock_config

        cfg = mock_config(store.data)
        cfg["instances"] = [{"id": "main", "name": "用户服务", "port": 8787,
                             "lan": False, "auto_start": False,
                             "routes": default_routes()}]
        srv = w.mock.get("main", "用户服务")
        ok, _msg = srv.start(cfg["instances"][0]["routes"], 8787, False, False)
        if ok:
            import urllib.request

            for path in ("/api/user", "/api/user", "/api/slow", "/api/boom", "/api/echo"):
                try:
                    urllib.request.urlopen(srv.url_for(path), timeout=5).read()
                except Exception:      # noqa: BLE001 —— 500 的那条本来就会抛
                    pass
        dlg = MockDialog(store, w.mock, w)
        dlg._refresh_mock_badge() if hasattr(dlg, "_refresh_mock_badge") else None
        dlg.resize(1150, 780)
        dlg.show()

        def done():
            save(dlg, "mock")
            dlg.tabs.set_current("logs", emit=True)
            dlg._on_tab("logs")
            QTimer.singleShot(400, lambda: (save(dlg, "mock-logs"), dlg.close(),
                                            w.mock.stop_all(), w._refresh_mock_badge(),
                                            next_()))

        QTimer.singleShot(650, done)

    # ---- 4b. 局域网二维码
    def s_qr(next_):
        from app.mock_panel import LanQrDialog
        from app.mock_server import MockServer

        from app.mock_server import default_routes

        srv = MockServer(instance="qr", name="二维码演示")
        srv.start(default_routes()[:1], 8799, False, True)
        dlg = LanQrDialog(srv, w)
        dlg.resize(560, 600)
        dlg.show()

        def done():
            save(dlg, "qr")
            dlg.close()
            srv.stop()
            next_()

        QTimer.singleShot(400, done)

    # ---- 4c. 命令面板
    def s_palette(next_):
        w.palette.open()

        def done():
            save(w, "palette")
            w.palette.close()
            next_()

        QTimer.singleShot(400, done)

    # ---- 5. 接口文档
    def s_doc(next_):
        from app.doc_window import DocDialog

        dlg = DocDialog(store, demo_get(), fake_response(), w)
        dlg.resize(1120, 900)
        dlg.show()

        def done():
            save(dlg, "doc")
            dlg.close()
            next_()

        QTimer.singleShot(700, done)

    # ---- 6. 设置 · 外观
    def s_settings(next_):
        from app.dialogs import SettingsDialog

        dlg = SettingsDialog(store, w, page="appearance")
        dlg.show()

        def done():
            save(dlg, "settings")
            dlg.close()
            next_()

        QTimer.singleShot(500, done)

    # ---- 6b. 云同步统计
    def s_cloud(next_):
        from app.cloud import snapshot_stats
        from app.dialogs import SettingsDialog

        dlg = SettingsDialog(store, w, page="cloud")
        dlg.resize(1000, 760)
        dlg.show()
        try:
            dlg._show_remote(snapshot_stats(store.data))
        except Exception:      # noqa: BLE001
            pass

        def done():
            save(dlg, "cloud")
            dlg.close()
            next_()

        QTimer.singleShot(500, done)

    # ---- 7. 浅色主题
    def s_light(next_):
        switch_to(get_tab)
        w._apply_theme("light")
        w.response.set_response(fake_response())

        def done():
            save(w, "light")
            w._apply_theme("dark")
            next_()

        QTimer.singleShot(650, done)

    steps = [s_main, s_body, s_tree, s_mock, s_qr, s_palette, s_doc, s_settings, s_cloud, s_light]

    def run(i=0):
        if i >= len(steps):
            app.quit()
            return
        steps[i](lambda: QTimer.singleShot(150, lambda: run(i + 1)))

    QTimer.singleShot(900, run)
    QTimer.singleShot(40000, app.quit)
    app.exec()

    for path in made:
        print(path)
    return 0 if len(made) == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
