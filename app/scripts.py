"""请求脚本：用 Qt 自带的 QJSEngine 执行前置 / 后置 JavaScript。

设计目标（对齐 Postman / Hoppscotch 但更轻）：

* 零额外依赖 —— 直接用 PyQt6.QtQml.QJSEngine，不引入 Node / dukpy。
* 沙箱而非裸引擎 —— 每次执行新建引擎，脚本拿不到 Python 对象，只能碰到
  我们显式注入的 `req` / `res` / `pw` / `console` / `test` 几个入口。
* 真超时 —— 执行前在循环体里插一个时间检查，`while (true) {}` 也会在 2 秒后
  中止并给出可读错误；不用后台线程，避免退出时线程残留把进程带崩。
* 可写环境变量 —— `pw.env.set` 先把改动收在临时表里，脚本跑完一次落盘，
  不中途写文件；`pw.env.get` 也读得到内置动态变量（$timestamp 等）。
* 可改请求 / 响应 —— `req` 与 `res` 是 Python dict 的 JS 镜像，执行完把变化读回来；
  后置脚本改 `res.status/body` 会反映到界面。写回时保留原有行的 enabled / type 等信息。
* 失败不影响发请求 —— 语法/运行/超时只记录到结果里，绝不抛出打断流程。
* 控制台分级 —— console.log / info / warn / error / debug 各自带级别，
  响应面板的「控制台」页按级别配色并显示图标。
* Python 模式 —— 前置 / 后置脚本可切换成 Python，API 与 JS 对齐（也支持
  req.set_header / res.status_text 这类 snake_case），import 走白名单，
  执行用 sys.settrace 做行数 + 时间双保险，死循环不会把界面卡死。

可用 API（脚本里直接写，不需要 import）：

    req.url / req.method / req.headers / req.body / req.params / req.cookies
    req.setHeader(name, value) / req.getHeader(name) / req.removeHeader(name)
    req.setParam(name, value) / req.removeParam(name) / req.setBody(text)
    req.json()                        —— 把 req.body 按 JSON 解析，失败返回 null

    pw.env.get(name) / pw.env.set(name, value) / pw.env.unset(name)
    pw.env.has(name) / pw.env.toObject()
    pw.env.resolve("{{token}}")       —— 用当前环境变量替换占位符

    console.log(...) / info / warn / error / debug
    test("名称", function () { ... })  —— 断言，抛错即失败，结果显示在控制台

后置脚本额外可用：

    res.status / res.statusText / res.time / res.body / res.headers
    res.getHeader(name) / res.setHeader(name, value) / res.removeHeader(name)
    res.json()                        —— 把 res.body 按 JSON 解析，失败返回 null
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from . import i18n

# 执行脚本的硬上限：脚本在独立线程里跑，主线程最多等这么久，超时直接判失败。
MAX_SCRIPT_MS = 2000
MAX_LOG_LINES = 200


class ScriptResult:
    """一次脚本执行的结果。ok=False 时 error 里是可读的错误信息。"""

    def __init__(self) -> None:
        self.ok = True
        self.error = ""
        self.logs: List[str] = []
        # 控制台条目：{"level": log|info|warn|error|debug|ok, "text": str}
        self.entries: List[Dict[str, str]] = []
        # 断言结果：{"name": str, "ok": bool, "error": str}
        self.tests: List[Dict[str, Any]] = []
        # pw.env.set 收集到的写入，等脚本跑完由主线程统一落盘
        self.env_writes: Dict[str, str] = {}
        self.timed_out = False

    @property
    def log_text(self) -> str:
        return "\n".join(self.logs)

    def add(self, level: str, text: str) -> None:
        if len(self.entries) >= MAX_LOG_LINES:
            return
        level = (level or "log").lower()
        text = str(text)
        self.entries.append({"level": level, "text": text})
        self.logs.append(text)


def _js(value: Any) -> str:
    """把 Python 值安全转成 JS 字面量（用于拼 console.log 的输出）。"""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _dynamic(name: str) -> Optional[str]:
    """内置动态变量：每次读取都重新取值，脚本里可以用 {{$timestamp}} 这类写法。"""
    from .store import dynamic_var

    return dynamic_var(name)


def _commit_env(store, writes: Dict[str, str]) -> None:
    """把脚本写入的环境变量落到当前环境，只落盘一次（在主线程调用）。"""
    if not writes or store is None:
        return
    env = store.active_environment()
    if env is None:
        env = {"id": "env_default", "name": "Default", "vars": []}
        store.environments.append(env)
        store.set_active_env(env["id"])
    rows = env.setdefault("vars", [])
    index = {r.get("key"): r for r in rows}
    for name, value in writes.items():
        row = index.get(name)
        if row is None:
            rows.append({"key": name, "value": str(value), "enabled": True})
        else:
            row["value"] = str(value)
            row["enabled"] = True
    store.save()


def _build_bridge(env_map: Dict[str, str], result: ScriptResult):
    """构造注入到 JS 全局的 Python 桥接对象。

    环境变量写入只进 result.env_writes，不直接改 store —— 脚本可能在后台线程
    里跑，跨线程改数据结构不安全（也是 macOS 上偶发硬崩的隐患）。
    """
    from PyQt6.QtCore import QObject, pyqtSlot

    def env_get(name: str) -> str:
        name = str(name)
        if name in result.env_writes:
            return result.env_writes[name]
        dyn = _dynamic(name)
        if dyn is not None:
            return dyn
        return str(env_map.get(name, ""))

    class _Bridge(QObject):
        @pyqtSlot(str, result=str)
        def envGet(self, name: str) -> str:
            return env_get(name)

        @pyqtSlot(str, str)
        def envSet(self, name: str, value: str) -> None:
            name = str(name).strip()
            if name:
                result.env_writes[name] = str(value)

        @pyqtSlot(str)
        def envUnset(self, name: str) -> None:
            result.env_writes.pop(str(name), None)
            result.entries.append({"level": "_unset", "text": str(name)})

        @pyqtSlot(str, result=str)
        def envResolve(self, text: str) -> str:
            from .store import resolve_vars

            merged = dict(env_map)
            merged.update(result.env_writes)
            return resolve_vars(str(text), merged)

        @pyqtSlot(str, result=str)
        def envHas(self, name: str) -> str:
            name = str(name)
            return "1" if (name in result.env_writes or name in env_map
                           or _dynamic(name) is not None) else ""

        @pyqtSlot(result=str)
        def envObject(self) -> str:
            merged = dict(env_map)
            merged.update(result.env_writes)
            try:
                return json.dumps(merged, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                return "{}"

        @pyqtSlot(str, str)
        def logLine(self, level: str, line: str) -> None:
            result.add(level, line)

        @pyqtSlot(str, bool, str)
        def testDone(self, name: str, ok: bool, error: str) -> None:
            result.tests.append({"name": str(name), "ok": bool(ok), "error": str(error)})
            if ok:
                result.add("ok", f"✓ {name}")
            else:
                result.add("error", f"✗ {name}" + (f" — {error}" if error else ""))
                if result.ok:
                    result.ok = False

    return _Bridge()


def _normalize_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """把请求 dict 拍平成脚本友好的结构，并把变动写回原 dict。"""
    headers = [{"name": str(h.get("key") or h.get("name") or ""),
                "value": str(h.get("value") or ""),
                "enabled": bool(h.get("enabled", True))}
               for h in (req.get("headers") or []) if isinstance(h, dict)]
    params = [{"name": str(p.get("key") or p.get("name") or ""),
               "value": str(p.get("value") or ""),
               "enabled": bool(p.get("enabled", True))}
              for p in (req.get("params") or []) if isinstance(p, dict)]
    cookies = [{"name": str(c.get("key") or c.get("name") or ""),
                "value": str(c.get("value") or ""),
                "enabled": bool(c.get("enabled", True))}
               for c in (req.get("cookies") or []) if isinstance(c, dict)]
    body = req.get("body") or {}
    return {
        "url": str(req.get("url") or ""),
        "method": str(req.get("method") or "GET"),
        "headers": headers,
        "params": params,
        "cookies": cookies,
        "body": str(body.get("raw") or ""),
        "name": str(req.get("name") or ""),
    }


def _merge_rows(orig: List[Dict[str, Any]], new: List[Dict[str, Any]],
                key_field: str = "key") -> List[Dict[str, Any]]:
    """把脚本改过的行合并回原始行：保留 type / description 等界面字段，
    只覆盖 key / value / enabled，尽量不把用户在界面里的设置弄丢。"""
    out: List[Dict[str, Any]] = []
    old = [dict(r) for r in (orig or []) if isinstance(r, dict)]
    used = [False] * len(old)
    for row in new:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        value = str(row.get("value") or "")
        enabled = bool(row.get("enabled", True))
        match = -1
        for i, cand in enumerate(old):
            if used[i]:
                continue
            if str(cand.get(key_field) or cand.get("name") or "") == name:
                match = i
                break
        if match >= 0:
            used[match] = True
            merged = old[match]
            merged[key_field] = name
            merged["value"] = value
            merged["enabled"] = enabled
        else:
            merged = {key_field: name, "value": value, "enabled": enabled}
        out.append(merged)
    return out


def _apply_request(view: Dict[str, Any], req: Dict[str, Any]) -> None:
    """把 JS 侧改过的字段写回请求 dict。"""
    for key in ("url", "method", "name", "body"):
        if key in view:
            if key == "body":
                req.setdefault("body", {})["raw"] = str(view[key])
            else:
                req[key] = str(view[key])
    if isinstance(view.get("headers"), list):
        req["headers"] = [r for r in _merge_rows(req.get("headers"), view["headers"])
                          if r.get("key")]
    if isinstance(view.get("params"), list):
        req["params"] = [r for r in _merge_rows(req.get("params"), view["params"])
                         if r.get("key")]
    if isinstance(view.get("cookies"), list):
        req["cookies"] = [r for r in _merge_rows(req.get("cookies"), view["cookies"])
                          if r.get("key")]


def _normalize_response(res: Any) -> Dict[str, Any]:
    headers: List[Dict[str, str]] = []
    for item in (getattr(res, "headers", None) or []):
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            headers.append({"name": str(item[0]), "value": str(item[1])})
    # Response.text 是方法不是属性：以前直接 str() 会得到 "<bound method ...>"，
    # 后置脚本里 res.body 永远解析不出 JSON（这就是「脚本判断不对」的根源之一）。
    text = getattr(res, "text", "")
    if callable(text):
        try:
            text = text()
        except Exception:  # noqa: BLE001
            text = ""
    return {
        "status": int(getattr(res, "status", 0) or 0),
        "statusText": str(getattr(res, "reason", "") or ""),
        "time": int(getattr(res, "elapsed", 0) or 0),
        "body": str(text or ""),
        "headers": headers,
    }


def _apply_response(view: Dict[str, Any], res: Any) -> None:
    """后置脚本对响应的修改写回 Response dataclass（能改的字段都改）。"""
    try:
        if "status" in view:
            res.status = int(view["status"])
        if "statusText" in view:
            res.reason = str(view["statusText"])
        if "time" in view:
            res.elapsed = int(view["time"])
        if "body" in view:
            # Response.text 是从 body 动态解码的 property，改 body 即可
            res.body = str(view["body"]).encode("utf-8")
        if isinstance(view.get("headers"), list) and getattr(res, "headers", None) is not None:
            res.headers = [(str(h.get("name") or ""), str(h.get("value") or ""))
                           for h in view["headers"] if isinstance(h, dict)]
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- Python 模式
# 目标不是做一个真沙箱（进程内无法挡住所有恶意代码），而是挡住「手滑」：
# 白名单 import、禁用 open/eval/exec、行数 + 时间双超时、错误带用户行号。
# 模块全部按需导入，不拖慢启动。

_SCRIPT_FILENAME = "<ocelot-script>"
_SAFE_IMPORTS = {
    "json", "re", "math", "random", "time", "datetime", "base64", "hashlib",
    "uuid", "collections", "itertools", "functools", "statistics", "decimal",
    "string", "enum", "dataclasses", "typing", "urllib.parse",
}
_BLOCKED_BUILTINS = {
    "open", "eval", "exec", "compile", "input", "breakpoint", "exit", "quit",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
}
_BLOCKED_NAMES = {"__builtins__", "__loader__", "__spec__", "__name__", "__file__"}


class _ScriptTimeout(BaseException):
    """用 BaseException，免得用户 `except Exception` 把超时吞掉。"""


class _ScriptSafetyError(Exception):
    """静态检测发现的禁止用法。"""


class _PyDict(dict):
    """既能 req['url'] 也能 req.url 的字典；写属性即写键。"""

    def __getattr__(self, key: str):
        if key in self:
            return self[key]
        raise AttributeError(key)

    def __setattr__(self, key: str, value) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self[key] = value


def _find_row(rows: List[Dict[str, Any]], name: str) -> int:
    low = str(name).lower()
    for i, row in enumerate(rows or []):
        if str(row.get("name") or "").lower() == low:
            return i
    return -1


class _ReqView(_PyDict):
    def set_header(self, name, value) -> None:
        rows = self.setdefault("headers", [])
        i = _find_row(rows, name)
        if i < 0:
            rows.append({"name": str(name), "value": str(value), "enabled": True})
        else:
            rows[i]["value"] = str(value)
            rows[i]["enabled"] = True

    def get_header(self, name) -> str:
        rows = self.get("headers") or []
        i = _find_row(rows, name)
        return "" if i < 0 else str(rows[i].get("value") or "")

    def remove_header(self, name) -> None:
        rows = self.get("headers") or []
        i = _find_row(rows, name)
        if i >= 0:
            rows.pop(i)

    def set_param(self, name, value) -> None:
        rows = self.setdefault("params", [])
        i = _find_row(rows, name)
        if i < 0:
            rows.append({"name": str(name), "value": str(value), "enabled": True})
        else:
            rows[i]["value"] = str(value)
            rows[i]["enabled"] = True

    def get_param(self, name) -> str:
        rows = self.get("params") or []
        i = _find_row(rows, name)
        return "" if i < 0 else str(rows[i].get("value") or "")

    def remove_param(self, name) -> None:
        rows = self.get("params") or []
        i = _find_row(rows, name)
        if i >= 0:
            rows.pop(i)

    def set_body(self, text) -> None:
        self["body"] = str(text)

    def json(self):
        try:
            return json.loads(self.get("body") or "")
        except Exception:  # noqa: BLE001
            return None

    # camelCase 兼容 JS 文档，迁移脚本不用改一行
    setHeader = set_header
    getHeader = get_header
    removeHeader = remove_header
    setParam = set_param
    getParam = get_param
    removeParam = remove_param
    setBody = set_body


class _ResView(_PyDict):
    _ALIASES = {"status_text": "statusText", "reason": "statusText",
                "text": "body", "elapsed": "time"}

    def __getattr__(self, key: str):
        return super().__getattr__(self._ALIASES.get(key, key))

    def __setattr__(self, key: str, value) -> None:
        super().__setattr__(self._ALIASES.get(key, key), value)

    def json(self):
        try:
            return json.loads(self.get("body") or "")
        except Exception:  # noqa: BLE001
            return None

    def get_header(self, name) -> str:
        i = _find_row(self.get("headers") or [], name)
        return "" if i < 0 else str(self["headers"][i].get("value") or "")

    def set_header(self, name, value) -> None:
        rows = self.setdefault("headers", [])
        i = _find_row(rows, name)
        if i < 0:
            rows.append({"name": str(name), "value": str(value)})
        else:
            rows[i]["value"] = str(value)

    def remove_header(self, name) -> None:
        rows = self.get("headers") or []
        i = _find_row(rows, name)
        if i >= 0:
            rows.pop(i)

    getHeader = get_header
    setHeader = set_header
    removeHeader = remove_header


class _PyEnv:
    def __init__(self, env_map: Dict[str, str], result: ScriptResult):
        self._env = env_map
        self._result = result

    def _merged(self) -> Dict[str, str]:
        out = dict(self._env)
        out.update(self._result.env_writes)
        return out

    def get(self, name) -> str:
        name = str(name)
        if name in self._result.env_writes:
            return self._result.env_writes[name]
        dyn = _dynamic(name)
        if dyn is not None:
            return dyn
        return str(self._env.get(name, ""))

    def set(self, name, value) -> None:
        name = str(name).strip()
        if name:
            self._result.env_writes[name] = str(value)

    def unset(self, name) -> None:
        name = str(name)
        self._result.env_writes.pop(name, None)
        self._result.entries.append({"level": "_unset", "text": name})

    def has(self, name) -> bool:
        name = str(name)
        return (name in self._result.env_writes or name in self._env
                or _dynamic(name) is not None)

    def resolve(self, text) -> str:
        from .store import resolve_vars

        return resolve_vars(str(text), self._merged())

    def to_object(self) -> Dict[str, str]:
        return self._merged()

    toObject = to_object


class _PyConsole:
    def __init__(self, result: ScriptResult):
        self._result = result

    @staticmethod
    def _line(args) -> str:
        parts = []
        for value in args:
            if isinstance(value, str):
                parts.append(value)
            elif value is None or isinstance(value, (int, float, bool)):
                parts.append(str(value))
            else:
                try:
                    parts.append(json.dumps(value, ensure_ascii=False, default=str))
                except Exception:  # noqa: BLE001
                    parts.append(str(value))
        return " ".join(parts)

    def _emit(self, level: str, args) -> None:
        self._result.add(level, self._line(args))

    def log(self, *args) -> None:
        self._emit("log", args)

    def info(self, *args) -> None:
        self._emit("info", args)

    def warn(self, *args) -> None:
        self._emit("warn", args)

    def error(self, *args) -> None:
        self._emit("error", args)

    def debug(self, *args) -> None:
        self._emit("debug", args)


def _assert_true(condition, message="assertion failed") -> None:
    if not condition:
        raise AssertionError(str(message))


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in _SAFE_IMPORTS:
        raise _ScriptSafetyError(i18n.trf("Python 脚本不允许导入 {name}", name=name))
    return __import__(name, globals, locals, fromlist, level)


def _check_python_safety(source: str):
    import ast

    tree = ast.parse(source, filename=_SCRIPT_FILENAME)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in _SAFE_IMPORTS:
                    raise _ScriptSafetyError(
                        i18n.trf("Python 脚本不允许导入 {name}", name=alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module not in _SAFE_IMPORTS:
                raise _ScriptSafetyError(
                    i18n.trf("Python 脚本不允许导入 {name}", name=module))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BLOCKED_BUILTINS:
                raise _ScriptSafetyError(
                    i18n.trf("Python 脚本不允许调用 {name}()", name=node.func.id))
        elif isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise _ScriptSafetyError(
                i18n.trf("Python 脚本不允许访问双下划线属性 {name}", name=node.id))
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                raise _ScriptSafetyError(
                    i18n.trf("Python 脚本不允许访问双下划线属性 {name}", name=attr))
    return tree


def _safe_builtins(console: _PyConsole) -> Dict[str, Any]:
    import builtins

    names = (
        "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
        "frozenset", "int", "isinstance", "issubclass", "iter", "len", "list",
        "map", "max", "min", "next", "range", "reversed", "round", "set",
        "slice", "sorted", "str", "sum", "tuple", "zip", "chr", "ord", "bin",
        "hex", "oct", "divmod", "pow", "Exception", "ValueError", "TypeError",
        "KeyError", "IndexError", "RuntimeError", "AssertionError",
        "StopIteration", "ZeroDivisionError",
    )
    out = {name: getattr(builtins, name) for name in names if hasattr(builtins, name)}
    out["print"] = console.log
    out["assert_true"] = _assert_true
    out["__import__"] = _safe_import
    return out


def _execute_python(source: str, req: Dict[str, Any], res: Any,
                    env_map: Dict[str, str], result: ScriptResult,
                    timeout_ms: int) -> None:
    import base64
    import datetime
    import hashlib
    import math
    import random
    import sys
    import traceback
    import uuid

    console = _PyConsole(result)
    env = _PyEnv(env_map, result)

    def make_test():
        def test(name, fn) -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                error = str(exc) or type(exc).__name__
                result.tests.append({"name": str(name), "ok": False, "error": error})
                result.add("error", "✗ %s — %s" % (name, error))
                result.ok = False
            else:
                result.tests.append({"name": str(name), "ok": True, "error": ""})
                result.add("ok", "✓ %s" % name)
        return test

    req_view = _ReqView(_normalize_request(req))
    ns: Dict[str, Any] = {
        "__builtins__": _safe_builtins(console),
        "req": req_view,
        "pw": type("PW", (), {"env": env})(),
        "console": console,
        "test": make_test(),
        "json": json, "re": __import__("re"), "math": math, "random": random,
        "time": time, "datetime": datetime, "base64": base64,
        "hashlib": hashlib, "uuid": uuid,
    }
    if res is not None:
        ns["res"] = _ResView(_normalize_response(res))

    try:
        tree = _check_python_safety(source)
        code = compile(tree, _SCRIPT_FILENAME, "exec")
    except SyntaxError as exc:
        msg = i18n.trf("第 {n} 行：{msg}", n=exc.lineno or 0,
                       msg="%s: %s" % (type(exc).__name__, exc.msg or exc))
        result.ok = False
        result.error = msg
        result.add("error", msg)
        return
    except _ScriptSafetyError as exc:
        result.ok = False
        result.error = str(exc)
        result.add("error", result.error)
        return

    counter = [0]
    budget = 400_000
    deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000.0

    def tracer(frame, event, arg):
        if event == "line":
            counter[0] += 1
            if (counter[0] >= budget
                    or ((counter[0] & 63) == 0 and time.monotonic() > deadline)):
                raise _ScriptTimeout()
        return tracer

    previous = sys.gettrace()
    sys.settrace(tracer)
    try:
        exec(code, ns)
    except _ScriptTimeout:
        result.ok = False
        result.timed_out = True
        result.error = i18n.trf(
            "脚本执行超过 {ms} 毫秒，已中止（检查是否有死循环）", ms=int(timeout_ms))
        result.add("error", result.error)
        return
    except BaseException as exc:  # noqa: BLE001  脚本出错绝不能打断请求
        tb = traceback.extract_tb(exc.__traceback__ or ())
        frame = next((f for f in tb if f.filename == _SCRIPT_FILENAME), None)
        msg = str(exc) or type(exc).__name__
        text = "%s: %s" % (type(exc).__name__, msg)
        result.ok = False
        result.error = (i18n.trf("第 {n} 行：{msg}", n=frame.lineno, msg=text)
                        if frame else text)
        result.add("error", result.error)
        return
    finally:
        sys.settrace(previous)

    changed = {key: value for key, value in req_view.items()}
    _apply_request(changed, req)
    if res is not None:
        changed_res = {key: value for key, value in ns["res"].items()}
        _apply_response(changed_res, res)


_PRELUDE = r"""
function __oc_str(a) {
  if (typeof a === 'object' && a !== null) {
    try { return JSON.stringify(a); } catch (e) { return String(a); }
  }
  return String(a);
}
function __oc_log(level, args) {
  var parts = [];
  for (var i = 0; i < args.length; i++) parts.push(__oc_str(args[i]));
  __bridge.logLine(level, parts.join(' '));
}
var console = {
  log:   function () { __oc_log('log', arguments); },
  info:  function () { __oc_log('info', arguments); },
  warn:  function () { __oc_log('warn', arguments); },
  error: function () { __oc_log('error', arguments); },
  debug: function () { __oc_log('debug', arguments); }
};

function test(name, fn) {
  try {
    fn();
    __bridge.testDone(String(name), true, '');
  } catch (e) {
    __bridge.testDone(String(name), false, String((e && e.message) || e));
  }
}

function __find(list, key, name) {
  for (var i = 0; i < list.length; i++)
    if (String(list[i][key]).toLowerCase() === String(name).toLowerCase()) return i;
  return -1;
}

req.json = function () { try { return JSON.parse(req.body); } catch (e) { return null; } };
req.setHeader = function (name, value) {
  var i = __find(req.headers, 'name', name);
  if (i < 0) req.headers.push({name: String(name), value: String(value), enabled: true});
  else { req.headers[i].value = String(value); req.headers[i].enabled = true; }
};
req.getHeader = function (name) {
  var i = __find(req.headers, 'name', name);
  return i < 0 ? '' : req.headers[i].value;
};
req.removeHeader = function (name) {
  var i = __find(req.headers, 'name', name);
  if (i >= 0) req.headers.splice(i, 1);
};
req.setParam = function (name, value) {
  var i = __find(req.params, 'name', name);
  if (i < 0) req.params.push({name: String(name), value: String(value), enabled: true});
  else { req.params[i].value = String(value); req.params[i].enabled = true; }
};
req.removeParam = function (name) {
  var i = __find(req.params, 'name', name);
  if (i >= 0) req.params.splice(i, 1);
};
req.setBody = function (text) { req.body = String(text); };

pw.env.set = function (name, value) { __bridge.envSet(String(name), String(value)); };
pw.env.get = function (name) { return __bridge.envGet(String(name)); };
pw.env.unset = function (name) { __bridge.envUnset(String(name)); };
pw.env.has = function (name) { return __bridge.envHas(String(name)) === '1'; };
pw.env.resolve = function (text) { return __bridge.envResolve(String(text)); };
pw.env.toObject = function () {
  try { return JSON.parse(__bridge.envObject()); } catch (e) { return {}; }
};
"""

_POST_PRELUDE = r"""
res.json = function () { try { return JSON.parse(res.body); } catch (e) { return null; } };
res.getHeader = function (name) {
  var i = __find(res.headers, 'name', name);
  return i < 0 ? '' : res.headers[i].value;
};
res.setHeader = function (name, value) {
  var i = __find(res.headers, 'name', name);
  if (i < 0) res.headers.push({name: String(name), value: String(value)});
  else res.headers[i].value = String(value);
};
res.removeHeader = function (name) {
  var i = __find(res.headers, 'name', name);
  if (i >= 0) res.headers.splice(i, 1);
};
"""


def _execute(source: str, req: Dict[str, Any], res: Any, env_map: Dict[str, str],
             result: ScriptResult) -> None:
    """在调用线程里建引擎并执行脚本；异常全部收进 result。"""
    from PyQt6.QtQml import QJSEngine

    engine = QJSEngine()
    bridge = _build_bridge(env_map, result)
    g = engine.globalObject()

    view = _normalize_request(req)
    g.setProperty("req", engine.toScriptValue(view))
    g.setProperty("pw", engine.toScriptValue({"env": {}}))
    if res is not None:
        g.setProperty("res", engine.toScriptValue(_normalize_response(res)))
    g.setProperty("__bridge", engine.toScriptValue(bridge))

    code = _PRELUDE + (_POST_PRELUDE if res is not None else "") + "\n" + source
    # 报错行号要换算成用户在编辑器里看到的行号（预置代码 + 超时检测占了几十行）
    marker = code.find("// __OC_USER_CODE__")
    offset = code[:marker].count("\n") if marker >= 0 else 0
    err = engine.evaluate(code)
    if err.isError():
        result.ok = False
        line = err.property("lineNumber").toInt() if err.property("lineNumber").isNumber() else 0
        if line > offset:
            line -= offset + 1
        msg = str(err.toString())
        result.error = (i18n.trf("第 {n} 行：{msg}", n=line, msg=msg)
                        if line else msg)
        result.add("error", result.error)
        return

    changed = g.property("req").toVariant()
    if isinstance(changed, dict):
        _apply_request(changed, req)
    if res is not None:
        changed_res = g.property("res").toVariant()
        if isinstance(changed_res, dict):
            _apply_response(changed_res, res)


def _instrument(source: str, budget_ms: int) -> str:
    """在循环体开头插一个超时检查，`while (true) {}` 也能被中止。

    为什么不用「后台线程 + 等 2 秒」：QJSEngine 的求值无法从外部打断，
    放弃的线程会一直跑，进程退出时 Qt 判定「线程仍在运行」直接 abort
    （macOS 上就是 bus error / 段错误）。改成在主线程跑 + 循环体插检查：
    到点抛一个可识别的异常，界面最多卡 2 秒，但没有线程残留。
    """
    head = f"var __oc_deadline = Date.now() + {int(budget_ms)};\n"
    head += (
        "function __oc_tick() {\n"
        "  if (Date.now() > __oc_deadline) throw new Error('__OC_TIMEOUT__');\n"
        "}\n"
    )

    def brace(m: "re.Match") -> str:
        return m.group(1) + "{ __oc_tick();"

    import re

    out = re.sub(r"((?:while|for)\s*\((?:[^()]|\([^()]*\))*\)\s*)\{", brace, source)
    out = re.sub(r"(\bdo\s*)\{", brace, out)
    # 标记用户代码起点：报错时把行号换算回用户看到的行号，而不是「第 74 行」
    return head + "// __OC_USER_CODE__\n" + out


_TIMEOUT_MARK = "__OC_TIMEOUT__"


def run_script(source: str, store, req: Dict[str, Any],
               res: Any = None, env_vars: Optional[Dict[str, str]] = None,
               timeout_ms: int = MAX_SCRIPT_MS,
               language: str = "javascript") -> ScriptResult:
    """执行一段脚本。res=None 表示前置；否则为后置。

    绝不抛异常：任何失败（语法、运行、超时）都进 result.error，
    让请求流程照常继续。环境变量的写入在跑完后统一落盘一次。
    """
    result = ScriptResult()
    src = (source or "").strip()
    if not src:
        return result

    env_map: Dict[str, str] = {}
    try:
        if env_vars:
            env_map.update({str(k): str(v) for k, v in env_vars.items()})
        if store is not None:
            for k, v in store.env_vars().items():
                env_map.setdefault(str(k), str(v))
    except Exception:  # noqa: BLE001
        pass

    try:
        if language == "python":
            _execute_python(src, req, res, env_map, result, timeout_ms)
        else:
            _execute(_instrument(src, timeout_ms), req, res, env_map, result)
    except Exception as exc:  # noqa: BLE001
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
        result.add("error", result.error)

    if _TIMEOUT_MARK in (result.error or ""):
        result.timed_out = True
        result.error = i18n.trf(
            "脚本执行超过 {ms} 毫秒，已中止（检查是否有死循环）", ms=int(timeout_ms))
        if result.entries and result.entries[-1].get("level") == "error":
            result.entries[-1]["text"] = result.error
        if result.logs and result.logs[-1] == "__OC_TIMEOUT__":
            result.logs[-1] = result.error

    # 环境变量统一落盘（unset 用 _unset 标记单独处理）
    unset = [e["text"] for e in result.entries if e.get("level") == "_unset"]
    result.entries = [e for e in result.entries if e.get("level") != "_unset"]
    if not result.timed_out and store is not None:
        try:
            _commit_env(store, result.env_writes)
            for name in unset:
                env = store.active_environment()
                if env:
                    env["vars"] = [r for r in env.get("vars", []) if r.get("key") != name]
                    store.save()
        except Exception:  # noqa: BLE001
            pass
    return result


def script_parts(scripts: Optional[Dict[str, Any]], phase: str):
    """取某一阶段真正要执行的源码与语言。老请求只有 pre/post，默认 JS。"""
    data = scripts or {}
    lang = str(data.get(f"{phase}_lang") or "javascript").lower()
    if lang not in ("javascript", "python"):
        lang = "javascript"
    key = f"{phase}_python" if lang == "python" else phase
    return str(data.get(key) or ""), lang


# ---------------------------------------------------------------- 默认示例
PRE_SAMPLE = """// Runs before the request is sent.
// Set a timestamp variable used by {{ts}} in the URL or headers.
pw.env.set("ts", String(Date.now()));
req.setHeader("X-Request-Source", "Ocelot");
console.log("Pre-request:", req.method, req.url);
"""

POST_SAMPLE = """// Runs after the response arrives.
// Save the token from the JSON body into the active environment.
console.log("Status:", res.status, "Time:", res.time + "ms");
var data = res.json();
if (data && data.token) {
  pw.env.set("token", data.token);
  test("响应包含 token", function () { if (!data.token) throw new Error("missing"); });
} else {
  console.warn("Response is not JSON");
}
"""
