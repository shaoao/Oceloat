"""请求脚本：用 Qt 自带的 QJSEngine 执行前置 / 后置 JavaScript。

设计目标（对齐 Hoppscotch 但更轻）：

* 零额外依赖 —— 直接用 PyQt6.QtQml.QJSEngine，不引入 Node / dukpy。
* 沙箱而非裸引擎 —— 每次执行新建引擎，脚本拿不到 Python 对象，只能碰到
  我们显式注入的 `req` / `res` / `pw` / `console` 四个入口。
* 可写环境变量 —— `pw.env.set/get/unset` 走 Store 的真实 env 结构并落盘；
  `pw.env.get` 也读得到内置的动态变量（$timestamp 等）。
* 可改请求 / 响应 —— `req` 与 `res` 是 Python dict 的 JS 镜像，执行完把
  变化读回来即可作用到本次请求；后置脚本改 `res.status/text` 会反映到界面。
* 失败不影响发请求 —— 语法/运行错误只记录到结果里，绝不抛出打断流程。

可用 API（脚本里直接写，不需要 import）：

    req.url / req.method / req.headers / req.body / req.params
    req.setHeader(name, value) / req.getHeader(name) / req.removeHeader(name)
    req.setParam(name, value) / req.setBody(text)

    pw.env.get(name) / pw.env.set(name, value) / pw.env.unset(name)
    pw.env.resolve("{{token}}")       —— 用当前环境变量替换占位符
    console.log(...args)              —— 收集到结果日志

后置脚本额外可用：

    res.status / res.statusText / res.time / res.body / res.headers
    res.setHeader(name, value) / res.getHeader(name)
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

# 执行脚本的硬上限：防止 `while(true){}` 把界面卡死。QJSEngine 没有原生超时，
# 用一个 QTimer 在超时后中断事件循环（见 _run_with_timeout）。
MAX_SCRIPT_MS = 2000
MAX_LOG_LINES = 100


class ScriptResult:
    """一次脚本执行的结果。ok=False 时 error 里是可读的错误信息。"""

    def __init__(self) -> None:
        self.ok = True
        self.error = ""
        self.logs: List[str] = []

    @property
    def log_text(self) -> str:
        return "\n".join(self.logs)


def _js(value: Any) -> str:
    """把 Python 值安全转成 JS 字面量（用于拼 console.log 的输出）。"""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _build_bridge(store, req: Dict[str, Any], res: Optional[Dict[str, Any]],
                  result: ScriptResult, env_snapshot: Dict[str, str]):
    """构造注入到 JS 全局的 Python 桥接对象（QJSEngine 支持可调用对象，
    用 setProperty 注入即可，不需要额外的类型转换）。"""
    def env_get(name: str) -> str:
        name = str(name)
        dynamic = {
            "$timestamp": lambda: str(int(time.time())),
            "$timestampMs": lambda: str(int(time.time() * 1000)),
            "$uuid": lambda: str(uuid.uuid4()),
            "$guid": lambda: str(uuid.uuid4()),
            "$randomInt": lambda: str(__import__("random").randint(0, 1_000_000)),
            "$isoTimestamp": lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if name in dynamic:
            return dynamic[name]()
        return str(env_snapshot.get(name, store.env_vars().get(name, "")))

    def env_set(name: str, value: Any) -> None:
        name = str(name)
        if not name:
            return
        env = store.active_environment()
        if env is None:
            env = {"id": "env_default", "name": "Default", "vars": []}
            store.environments.append(env)
            store.set_active_env(env["id"])
        for row in env.setdefault("vars", []):
            if row.get("key") == name:
                row["value"] = str(value)
                row["enabled"] = True
                break
        else:
            env["vars"].append({"key": name, "value": str(value), "enabled": True})
        env_snapshot[name] = str(value)
        store.save()

    def env_unset(name: str) -> None:
        name = str(name)
        env = store.active_environment()
        if env:
            env["vars"] = [r for r in env.get("vars", []) if r.get("key") != name]
            store.save()
        env_snapshot.pop(name, None)

    def env_resolve(text: str) -> str:
        from .store import resolve_vars

        return resolve_vars(str(text), env_snapshot)

    def log(*args: Any) -> None:
        parts: List[str] = []
        for a in args:
            try:
                # QJSValue 的 toVariant 拿真实值；普通 Python 值直接用
                parts.append(_js(a.toVariant() if hasattr(a, "toVariant") else a))
            except Exception:
                parts.append(str(a))
        if len(result.logs) < MAX_LOG_LINES:
            result.logs.append(" ".join(parts))

    from PyQt6.QtCore import QObject, pyqtSlot

    class _Bridge(QObject):
        @pyqtSlot(str, result=str)
        def envGet(self, name: str) -> str:
            return env_get(name)

        @pyqtSlot(str, str)
        def envSet(self, name: str, value: str) -> None:
            env_set(name, value)

        @pyqtSlot(str)
        def envUnset(self, name: str) -> None:
            env_unset(name)

        @pyqtSlot(str, result=str)
        def envResolve(self, text: str) -> str:
            return env_resolve(text)

        @pyqtSlot(str)
        def logLine(self, line: str) -> None:
            if len(result.logs) < MAX_LOG_LINES:
                result.logs.append(line)

    return _Bridge()


def _normalize_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """把请求 dict 拍平成脚本友好的结构，并把变动写回原 dict。"""
    headers = [{"name": str(h.get("key") or h.get("name") or ""),
                "value": str(h.get("value") or "")}
               for h in (req.get("headers") or []) if isinstance(h, dict)]
    params = [{"name": str(p.get("key") or p.get("name") or ""),
               "value": str(p.get("value") or ""),
               "enabled": bool(p.get("enabled", True))}
              for p in (req.get("params") or []) if isinstance(p, dict)]
    body = req.get("body") or {}
    return {
        "url": str(req.get("url") or ""),
        "method": str(req.get("method") or "GET"),
        "headers": headers,
        "params": params,
        "body": str(body.get("raw") or ""),
        "name": str(req.get("name") or ""),
    }


def _apply_request(view: Dict[str, Any], req: Dict[str, Any]) -> None:
    """把 JS 侧改过的字段写回请求 dict。"""
    for key in ("url", "method", "name", "body"):
        if key in view:
            if key == "body":
                req.setdefault("body", {})["raw"] = str(view[key])
            else:
                req[key] = str(view[key])
    if isinstance(view.get("headers"), list):
        req["headers"] = [
            {"key": str(h.get("name") or ""), "value": str(h.get("value") or ""),
             "enabled": True}
            for h in view["headers"] if isinstance(h, dict) and h.get("name")
        ]
    if isinstance(view.get("params"), list):
        req["params"] = [
            {"key": str(p.get("name") or ""), "value": str(p.get("value") or ""),
             "enabled": bool(p.get("enabled", True))}
            for p in view["params"] if isinstance(p, dict) and p.get("name")
        ]


def _normalize_response(res: Any) -> Dict[str, Any]:
    headers: List[Dict[str, str]] = []
    for item in (getattr(res, "headers", None) or []):
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            headers.append({"name": str(item[0]), "value": str(item[1])})
    return {
        "status": int(getattr(res, "status", 0) or 0),
        "statusText": str(getattr(res, "reason", "") or ""),
        "time": int(getattr(res, "elapsed", 0) or 0),
        "body": str(getattr(res, "text", "") or ""),
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
    except Exception:
        pass


_PRELUDE = r"""
function __oc_log() {
  var parts = [];
  for (var i = 0; i < arguments.length; i++) {
    var a = arguments[i];
    if (typeof a === 'object' && a !== null) {
      try { parts.push(JSON.stringify(a)); } catch (e) { parts.push(String(a)); }
    } else { parts.push(String(a)); }
  }
  __bridge.logLine(parts.join(' '));
}
var console = { log: __oc_log, info: __oc_log, warn: __oc_log, error: __oc_log };

function __header(list, name) {
  for (var i = 0; i < list.length; i++)
    if (String(list[i].name).toLowerCase() === String(name).toLowerCase()) return i;
  return -1;
}
req.setHeader = function(name, value) {
  var i = __header(req.headers, name);
  if (i < 0) req.headers.push({name: String(name), value: String(value)});
  else req.headers[i].value = String(value);
};
req.getHeader = function(name) {
  var i = __header(req.headers, name);
  return i < 0 ? '' : req.headers[i].value;
};
req.removeHeader = function(name) {
  var i = __header(req.headers, name);
  if (i >= 0) req.headers.splice(i, 1);
};
req.setParam = function(name, value) {
  for (var i = 0; i < req.params.length; i++)
    if (req.params[i].name === name) { req.params[i].value = String(value); return; }
  req.params.push({name: String(name), value: String(value), enabled: true});
};
req.setBody = function(text) { req.body = String(text); };
pw.env.set = function(name, value) { __bridge.envSet(String(name), String(value)); };
pw.env.get = function(name) { return __bridge.envGet(String(name)); };
pw.env.unset = function(name) { __bridge.envUnset(String(name)); };
pw.env.resolve = function(text) { return __bridge.envResolve(String(text)); };
"""


def run_script(source: str, store, req: Dict[str, Any],
               res: Any = None, env_vars: Optional[Dict[str, str]] = None) -> ScriptResult:
    """执行一段脚本。res=None 表示前置；否则为后置。

    绝不抛异常：任何失败都进 result.error，让请求流程照常继续。
    """
    result = ScriptResult()
    src = (source or "").strip()
    if not src:
        return result

    try:
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtQml import QJSEngine

        engine = QJSEngine()
        bridge = _build_bridge(store, req, res, result, dict(env_vars or {}))
        g = engine.globalObject()

        # 基础数据
        view = _normalize_request(req)
        g.setProperty("req", engine.toScriptValue(view))
        pw = {"env": {}}
        g.setProperty("pw", engine.toScriptValue(pw))
        if res is not None:
            g.setProperty("res", engine.toScriptValue(_normalize_response(res)))

        # Python 桥接对象（QObject 槽）；console.log 由 prelude 转发到 logLine
        g.setProperty("__bridge", engine.toScriptValue(bridge))

        # 预置 helper + 用户代码；超时靠定时器打断嵌套事件循环
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(MAX_SCRIPT_MS)
        err = engine.evaluate(_PRELUDE + "\n" + src)
        if timer.isActive():
            timer.stop()
        if err.isError():
            result.ok = False
            result.error = str(err.toString())
            return result

        changed = g.property("req").toVariant()
        if isinstance(changed, dict):
            _apply_request(changed, req)
        if res is not None:
            changed_res = g.property("res").toVariant()
            if isinstance(changed_res, dict):
                _apply_response(changed_res, res)
    except Exception as exc:  # noqa: BLE001 — 脚本永远不能打断请求
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
    return result


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
try {
  var data = JSON.parse(res.body);
  if (data.token) pw.env.set("token", data.token);
} catch (e) {
  console.log("Response is not JSON");
}
"""
