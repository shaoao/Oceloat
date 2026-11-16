"""开发用截图脚本：离屏渲染主窗口若干状态，便于视觉验收。

用法：python3 tools/shot.py [状态...]
状态：main / palette / settings / env / code / light / response
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import store as store_mod
from app.main_window import MainWindow  # noqa: E402
from app.store import Store  # noqa: E402
from app.theme import apply_theme, theme_by_name  # noqa: E402

OUT = "/tmp/ocelot_shots"
SANDBOX = os.path.join(OUT, "sandbox")


def _isolate_state():
    """截图时不要改动用户真实会话：把状态文件指到临时目录。

    注意：Store.load 的默认参数在导入时就绑定了真实路径，因此必须显式传参。
    """
    from pathlib import Path

    os.makedirs(SANDBOX, exist_ok=True)
    real = store_mod.STATE_FILE
    sandbox = Path(SANDBOX) / "state.json"
    if not sandbox.exists() and real.exists():
        import shutil

        shutil.copy(real, sandbox)
    if sandbox.exists():
        data = json.loads(sandbox.read_text("utf-8"))
        data["open_tabs"] = []          # 每次从干净会话开始
        data.setdefault("settings", {})["theme"] = "dark"
        sandbox.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    return sandbox


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    state_path = _isolate_state()
    states = sys.argv[1:] or ["main"]
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    store = Store.load(state_path)
    apply_theme(app, theme_by_name(store.settings.get("theme", "dark")))
    w = MainWindow(store)
    w.resize(1320, 840)
    w.show()

    results = []

    def grab(name: str):
        pm = w.grab()
        path = os.path.join(OUT, f"{name}.png")
        pm.save(path)
        results.append(path)

    def find_node(keyword: str):
        for n, _ in store.walk():
            if n.get("type") == "request" and keyword in (n.get("name") or ""):
                return n
        return None

    def run_states(i: int = 0):
        if i >= len(states):
            app.quit()
            return
        state = states[i]
        if state == "main":
            node = find_node("Query Params")
            if node:
                w._open_from_sidebar(node)
            QTimer.singleShot(420, lambda: (grab("main"), run_states(i + 1)))
            return
        elif state == "palette":
            w.show_palette()
            QTimer.singleShot(320, lambda: (grab("palette"), run_states(i + 1)))
            return
        elif state == "light":
            node = find_node("Query Params")
            if node:
                w._open_from_sidebar(node)
            w._apply_theme("light")
            QTimer.singleShot(420, lambda: (grab("light"), run_states(i + 1)))
            return
        elif state == "live":
            node = None
            for n, _ in store.walk():
                if n.get("type") == "request" and "Query Params" in (n.get("name") or ""):
                    node = n
                    break
            if node:
                w._open_from_sidebar(node)
            w.send_current()

            def after():
                grab("live")
                run_states(i + 1)

            QTimer.singleShot(7000, after)
            return
        elif state in ("body", "headers", "auth", "params"):
            node = None
            for n, _ in store.walk():
                if n.get("type") == "request" and "JSON Body" in (n.get("name") or ""):
                    node = n
                    break
            if node:
                w._open_from_sidebar(node)
                w.editor.tabs.set_current(state if state != "params" else "params", emit=True)
                w.editor._on_tab(state)
            QTimer.singleShot(420, lambda: (grab(state), run_states(i + 1)))
            return
        elif state == "welcome":
            for tid in [t["id"] for t in list(w.tabs_data)]:
                w.close_tab(tid)
            QTimer.singleShot(420, lambda: (grab("welcome"), run_states(i + 1)))
            return
        elif state == "history":
            w.sidebar._on_mode("history")
            QTimer.singleShot(380, lambda: (grab("history"), run_states(i + 1)))
            return
        elif state == "form":
            node = None
            for n, _ in store.walk():
                if n.get("type") == "request" and "JSON Body" in (n.get("name") or ""):
                    node = n
                    break
            if node:
                w._open_from_sidebar(node)
                w.editor.body.modes.set_current("form", emit=True)
                w.editor.body.form.set_rows([
                    {"key": "title", "value": "Ocelot", "enabled": True},
                    {"key": "avatar", "value": "@/Users/shaoao/Desktop/avatar.png", "enabled": True},
                    {"key": "tags", "value": "api,client", "enabled": False},
                ])
                w.editor.body._on_mode("form")
                w.editor._on_tab("body")
            QTimer.singleShot(420, lambda: (grab("form"), run_states(i + 1)))
            return
        elif state in ("tree", "rheaders", "pretty"):
            from app.http_client import Response as RT

            body = b'{"id":42,"name":"Ocelot","tags":["api","client"],"owner":{"id":7,"login":"shaoao","site_admin":false},"stars":1280,"license":null}'
            resp = RT(status=200, reason="OK", headers=[
                ("content-type", "application/json; charset=utf-8"),
                ("content-length", str(len(body))), ("server", "nginx/1.25.3"),
                ("cache-control", "max-age=60"), ("x-ratelimit-remaining", "57"),
            ], body=body, elapsed=96, size=len(body), url="https://api.example.com/repos/ocelot",
                content_type="application/json")
            w.response.set_response(resp)
            key = {"tree": "tree", "rheaders": "headers", "pretty": "pretty"}.get(state, "pretty")
            w.response.tabs.set_current(key, emit=True)
            w.response._on_tab(key)
            QTimer.singleShot(420, lambda: (grab(state), run_states(i + 1)))
            return
        elif state in ("diff", "extract"):
            from app.http_client import Response as R2

            node = find_node("Query Params")
            if node:
                w._open_from_sidebar(node)
            before = b'{"id":42,"name":"Ocelot","tags":["api","client"],"stars":1280,"license":null}'
            after = (b'{\n  "id": 42,\n  "name": "Ocelot",\n  "tags": ["api", "client", "qt"],\n'
                     b'  "stars": 1304,\n  "license": null,\n  "homepage": "https://ocelot.dev"\n}')
            common = dict(reason="OK", headers=[
                ("content-type", "application/json; charset=utf-8"),
                ("content-length", str(len(after))), ("server", "nginx/1.25.3"),
                ("x-ratelimit-remaining", "57"),
            ], url="https://api.example.com/repos/ocelot", content_type="application/json")
            w.response.set_response(R2(status=200, body=before, elapsed=96,
                                       size=len(before), **common))
            w.response.set_response(R2(status=200, body=after, elapsed=141,
                                       size=len(after), **common))
            w.response.path_edit.setText("tags[2]")
            key = state
            w.response.tabs.set_current(key, emit=True)
            w.response._on_tab(key)
            QTimer.singleShot(420, lambda: (grab(state), run_states(i + 1)))
            return
        elif state == "cookies":
            from app.http_client import Response as R

            body = b'{"ok":true}'
            resp = R(status=201, reason="Created", headers=[
                ("content-type", "application/json"), ("content-length", str(len(body))),
                ("set-cookie", "sid=9f2a; Path=/; HttpOnly"), ("set-cookie", "theme=dark; Path=/; Max-Age=86400"),
                ("location", "/api/v1/items/42"), ("x-request-id", "c1f0-4b2e-9d"),
            ], body=body, elapsed=87, size=len(body), url="https://api.example.com/v1/items",
                content_type="application/json",
                cookies=[{"name": "sid", "value": "9f2a", "domain": "api.example.com", "path": "/",
                          "expires": "session", "secure": False, "http_only": True},
                         {"name": "theme", "value": "dark", "domain": "api.example.com", "path": "/",
                          "expires": "2026-11-17 17:00", "secure": False, "http_only": False}])
            w.response.set_response(resp)
            w.response.tabs.set_current("cookies", emit=True)
            w.response._on_tab("cookies")
            QTimer.singleShot(420, lambda: (grab("cookies"), run_states(i + 1)))
            return
        elif state == "curl":
            from app.dialogs import ImportCurlDialog

            dlg = ImportCurlDialog(w)
            dlg.edit.setPlainText("curl 'https://api.example.com/v1/users?page=2' \\\n"
                                  "  -X POST \\\n"
                                  "  -H 'Content-Type: application/json' \\\n"
                                  "  -H 'Authorization: Bearer tok-42' \\\n"
                                  "  --data-raw '{\"name\": \"Reqly\"}'")
            dlg.show()
            QTimer.singleShot(320, lambda: (grab_widget(dlg, "curl"), dlg.close(), run_states(i + 1)))
            return
        elif state == "settings":
            from app.dialogs import SettingsDialog

            dlg = SettingsDialog(store, w)
            dlg.show()
            QTimer.singleShot(320, lambda: (grab_widget(dlg, "settings"), dlg.close(), run_states(i + 1)))
            return
        elif state == "env":
            from app.dialogs import EnvDialog

            dlg = EnvDialog(store, w)
            dlg.show()
            QTimer.singleShot(320, lambda: (grab_widget(dlg, "env"), dlg.close(), run_states(i + 1)))
            return
        elif state == "code":
            from app.dialogs import CodeDialog

            req = (w.current_tab() or {}).get("request") or {}
            dlg = CodeDialog(req, store.env_vars(), store.settings, w)
            dlg.show()
            QTimer.singleShot(320, lambda: (grab_widget(dlg, "code"), dlg.close(), run_states(i + 1)))
            return
        elif state == "response":
            from app.http_client import Response

            if not w.tabs_data:
                w.new_request()
            body = b'{"slideshow":{"author":"Yours Truly","date":"date of publication","slides":[{"title":"Wake up to WonderWidgets!","type":"all"},{"items":["Why <em>WonderWidgets</em> are great","Who <em>buys</em> WonderWidgets"],"title":"Overview","type":"all"}],"title":"Sample Slide Show"}}'
            resp = Response(status=200, reason="OK", headers=[
                ("content-type", "application/json; charset=utf-8"),
                ("content-length", str(len(body))), ("server", "nginx/1.25.3"),
                ("cache-control", "no-store"), ("set-cookie", "session=abc123; Path=/; HttpOnly"),
            ], body=body, elapsed=142, size=len(body),
                url="https://httpbin.org/json", content_type="application/json; charset=utf-8",
                cookies=[{"name": "session", "value": "abc123", "domain": "httpbin.org",
                          "path": "/", "expires": "session", "secure": False, "http_only": True}])
            w.response.set_response(resp)
            QTimer.singleShot(420, lambda: (grab("response"), run_states(i + 1)))
            return
        run_states(i + 1)

    def grab_widget(widget, name):
        widget.grab().save(os.path.join(OUT, f"{name}.png"))
        results.append(os.path.join(OUT, f"{name}.png"))

    QTimer.singleShot(900, lambda: run_states(0))
    QTimer.singleShot(15000, app.quit)
    code = app.exec()
    print("\n".join(results))
    return code


if __name__ == "__main__":
    sys.exit(main())
