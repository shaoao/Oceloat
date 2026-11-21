"""GraphQL / Git Diff 自测：纯逻辑 + 真实发送（本地回环服务）+ 界面装配。

用法：python3 tools/check_gql_git.py      （不碰真实数据目录）
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OCELOT_NO_TEE", "1")

from app import gitsync, graphql as gql  # noqa: E402

FAILS, OKS = [], []


def check(name, cond, detail=""):
    (OKS if cond else FAILS).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {detail if not cond else ''}")


USER = {"kind": "OBJECT", "name": "User", "fields": [
    {"name": "id", "args": [], "type": {"kind": "SCALAR", "name": "ID"}},
    {"name": "name", "args": [], "type": {"kind": "SCALAR", "name": "String"}},
    {"name": "friends", "args": [], "type": {"kind": "LIST", "name": None,
                                             "ofType": {"kind": "OBJECT", "name": "User"}}}]}
SCHEMA = {"data": {"__schema": {
    "queryType": {"name": "Query"}, "mutationType": {"name": "Mutation"}, "subscriptionType": None,
    "types": [
        {"kind": "OBJECT", "name": "Query", "fields": [
            {"name": "user", "args": [{"name": "id", "type": {"kind": "NON_NULL", "name": None,
                                                              "ofType": {"kind": "SCALAR", "name": "ID"}}}],
             "type": {"kind": "OBJECT", "name": "User"}}]},
        {"kind": "OBJECT", "name": "Mutation", "fields": [
            {"name": "rename", "args": [], "type": {"kind": "OBJECT", "name": "User"}}]},
        USER, {"kind": "SCALAR", "name": "ID"}, {"kind": "SCALAR", "name": "String"}]}}}
SEEN = {}


class _Gql(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        SEEN["body"] = json.loads(raw or b"{}")
        SEEN["ct"] = self.headers.get("Content-Type", "")
        q = SEEN["body"].get("query", "")
        out = SCHEMA if "__schema" in q else {"data": {"user": {"id": "1"}}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def logic() -> None:
    print("— GraphQL 逻辑")
    s = gql.Schema(SCHEMA)
    q = "query Q($id: ID!) {\n  user(id: $id) {\n    fr"
    check("嵌套补全", [r["name"] for r in gql.suggest(s, q, len(q))[1]] == ["friends"])
    q = "mutation { "
    check("变更根补全", [r["name"] for r in gql.suggest(s, q, len(q))[1]] == ["rename"])
    check("骨架提取必填参数", "query User($id: ID!)" in gql.skeleton(s, "user"))
    b = {"mode": "graphql", "raw": "query A{a} query B{b}", "gql_vars": '{"x":1}', "gql_op": "B"}
    check("载荷 operationName", gql.payload(b)["operationName"] == "B")
    check("变量同步", '"id": ""' in gql.sync_variables("query($id: ID!){a}", ""))
    check("括号校验", "没有闭合" in gql.check("{ a {"))
    check("errors 摘取", gql.response_errors(b'{"errors":[{"message":"x"}]}') == ["x"])

    print("— Git diff 逻辑")
    old = {"id": "abc123", "type": "folder", "name": "A", "children": [
        {"id": "r1", "type": "request", "name": "L", "method": "GET", "url": "/a",
         "headers": [{"key": "Authorization", "value": "s1"}]}]}
    new = copy.deepcopy(old)
    new["children"][0]["url"] = "/b"
    new["children"][0]["headers"][0]["value"] = "s2"
    d = gitsync.semantic_diff(old, new)
    check("请求级 diff", gitsync.stats(d) == {"added": 0, "removed": 0, "changed": 1})
    check("密钥打码", "s1" not in json.dumps(d, ensure_ascii=False))
    check("导出稳定", gitsync.dumps(old) == gitsync.dumps(dict(old, saved=9)))
    with tempfile.TemporaryDirectory() as tmp:
        p = gitsync.write(tmp, old)
        mtime = p.stat().st_mtime_ns
        gitsync.write(tmp, old)
        check("内容没变不重写", p.stat().st_mtime_ns == mtime)
        gitsync.auto_write({"git": {"auto": True, "dir": tmp}}, [new])
        check("自动写入", gitsync.loads(p.read_text())["children"][0]["url"] == "/b")
        if gitsync.git_path():
            ok, msg = gitsync.commit(Path(tmp), [p], "init")
            check("git 提交", ok, msg)
            check("HEAD 可读", gitsync.loads(gitsync.show_at(Path(tmp), "HEAD", p)) is not None)
        else:
            print("  SKIP  未检测到 git，跳过提交测试")


def ui() -> None:
    from PyQt6.QtWidgets import QApplication

    print("— 界面与发送")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from app.http_client import ApiClient
    from app.codegen import to_curl
    from app.store import Store
    from app.transfer import _import_postman_body, _postman_body
    from app.request_panel import BodyPage, RequestEditor

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Gql)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/graphql"

    with tempfile.TemporaryDirectory() as tmp:
        store = Store.load(Path(tmp) / "state.json")
        Store._active = store
        req = {"id": "x", "method": "POST", "url": url, "params": [], "headers": [],
               "cookies": [], "auth": {"type": "none"}, "scripts": {},
               "body": {"mode": "graphql", "raw": "query U($id: ID!){ user(id:$id){ id } }",
                        "gql_vars": '{"id": "{{uid}}"}', "gql_op": ""}}
        client = ApiClient()
        client.set_store(store)
        got = {}
        client.finished.connect(lambda r: got.setdefault("r", r))
        client.send(req, {}, {"uid": "42"})
        import time
        end = time.time() + 8
        while "r" not in got and time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        check("GraphQL 真实发送", got.get("r") is not None and got["r"].status == 200)
        check("载荷为标准 JSON", SEEN.get("body", {}).get("variables") == {"id": "42"})
        check("Content-Type 为 JSON", SEEN.get("ct", "").startswith("application/json"))
        check("cURL 带 query", '"query"' in to_curl(req, {"uid": "1"}, {}))
        pm = _postman_body(req["body"])
        back = _import_postman_body(pm)
        check("Postman 往返不丢", back["mode"] == "graphql" and back["raw"] == req["body"]["raw"]
              and json.loads(back["gql_vars"]) == {"id": "{{uid}}"})

        page = BodyPage()
        page.load(req["body"])
        check("请求体页切到 GraphQL", page.stack.current() == "gql")
        dumped = page.dump()
        check("请求体 dump 保真", dumped["raw"] == req["body"]["raw"] and dumped["gql_vars"]
              == req["body"]["gql_vars"])
        page.load({"mode": "xml", "raw": "<a><b>1</b></a>"})
        try:
            page._format()
            check("XML 格式化不再抛 ImportError", "\n" in page.code.toPlainText())
        except ImportError as exc:
            check("XML 格式化不再抛 ImportError", False, str(exc))

        ed = RequestEditor(store)
        ed.load(copy.deepcopy(req))
        ed.body.gql.fetch_schema()
        end = time.time() + 8
        while ed.body.gql.schema() is None and time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        check("内省拉取 Schema", ed.body.gql.schema() is not None)
        gq = ed.body.gql
        gq.query.setPlainText("{ user(id: 1) { na")
        cur = gq.query.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        gq.query.setTextCursor(cur)
        gq.query.complete(force=True)
        check("编辑器补全", [r["name"] for r in gq.query._rows] == ["name"])

        from app.git_panel import GitDialog, render
        store.data["collections"] = [{"id": "c1", "type": "folder", "name": "C",
                                      "children": [req]}]
        store.settings["git"] = {"dir": tmp + "/repo"}
        dlg = GitDialog(store)
        check("Git 窗口打开", dlg.list.count() == 1)
        dlg._write(commit=False)
        check("写入后无改动", "已同步" in dlg.note.text() or "0" in dlg.list.item(0).text()
              or dlg.list.item(0).text() == "C", dlg.list.item(0).text())
        check("diff 渲染", "没有改动" in render([]))
        dlg.deleteLater()
    srv.shutdown()


if __name__ == "__main__":
    logic()
    try:
        ui()
    except Exception:
        import traceback
        traceback.print_exc()
        FAILS.append("ui 异常")
    print(f"\n{len(OKS)} 通过 · {len(FAILS)} 失败")
    sys.exit(1 if FAILS else 0)
