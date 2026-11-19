"""本地 Mock 服务：在 127.0.0.1（或 0.0.0.0）上起一个真的 HTTP 服务，按规则返回响应。

为什么要有它：
- 「Mock 数据」如果只是把公开接口的地址填进地址栏，那算不上 Mock —— 断网、限流、
  字段改动都轮不到你控制；
- 这里用标准库 `ThreadingHTTPServer` 起一个服务，路由、状态码、延迟、
  响应体全都由你定，前端、单元测试、手机都能直接连；
- 不引第三方依赖、不写临时文件，停掉就干净退出。

一条路由能做的事（都在 state.json 里，纯 JSON）：
    {"id","name","group","method","path","status","content_type","body",
     "delay","enabled","echo","rules":[...]}

- **分组**：`group` 支持 `用户/登录` 这种斜杠层级，面板里渲染成树；
- **延迟**：`delay` 毫秒后才响应，用来测 Loading、骨架屏、超时逻辑；
- **动态数据**：响应体里写 `{{@name}}` `{{@id}}` `{{@uuid}}` `{{@now}}` 之类的占位符，
  每个请求现算一次，不会永远返回同一份死数据；
- **条件规则**：`rules` 里按请求头 / 查询参数 / 请求体 / 方法匹配，
  第一条命中的规则可以覆盖状态码、延迟与响应体；
- **回显**：`echo=True` 把收到的请求原样返回，用来查「客户端到底发了什么」；
- **多实例**：一个进程里可以有多个 MockServer，各占一个端口（见 MockHub）；
- **局域网**：`lan=True` 时监听 0.0.0.0，手机 / 别的电脑用局域网 IP 直连。
"""
from __future__ import annotations

from . import i18n

import json
import random
import re
import socket
import threading
import time
import uuid as _uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote_plus, urlsplit

DEFAULT_PORT = 8787
PING_PATH = "/__ocelot__/ping"
LOG_LIMIT = 300
ECHO_JSON = json.dumps({
    "ok": True,
    "message": "来自 Ocelot 本地 Mock 服务",
    "items": [
        {"id": 1, "name": "mock-row-1", "enabled": True},
        {"id": 2, "name": "mock-row-2", "enabled": False},
    ],
}, ensure_ascii=False, indent=2)

SAMPLE_USER = json.dumps({
    "id": 7,
    "name": "Ada Lovelace",
    "role": "admin",
    "token": "mock-token-please-replace",
}, ensure_ascii=False, indent=2)

PROFILE_JSON = json.dumps({
    "id": "{{@id}}",
    "name": "{{@name}}",
    "nickname": "{{@cname}}",
    "email": "{{@email}}",
    "phone": "{{@phone}}",
    "city": "{{@city}}",
    "avatar": "{{@avatar(120,120)}}",
    "vip": "{{@bool}}",
    "score": "{{@int(60,100)}}",
    "created_at": "{{@now}}",
}, ensure_ascii=False, indent=2)

AUTH_RULE_BODY = json.dumps({
    "code": 0,
    "vip": True,
    "message": "VIP 用户，可见完整字段",
    "data": {"plan": "enterprise", "seats": 80, "expires": "2027-01-01"},
}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 占位符
_FIRST = ["Ada", "Alan", "Grace", "Linus", "Ken", "Barbara", "Donald", "Margaret",
          "Edsger", "Katherine", "Tim", "Radia"]
_LAST = ["Lovelace", "Turing", "Hopper", "Torvalds", "Thompson", "Liskov", "Knuth",
         "Hamilton", "Dijkstra", "Johnson", "Berners", "Perlman"]
_CN_FIRST = ["伟", "芳", "娜", "敏", "静", "磊", "洋", "勇", "艳", "杰", "涛", "明"]
_CN_LAST = ["王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙"]
_CITY = ["北京", "上海", "杭州", "深圳", "成都", "广州", "南京", "武汉", "西安", "苏州"]
_COMPANY = ["Ocelot Labs", "Nimbus", "Lumen", "Pinecone", "Vertex", "Hollow", "Kite"]
_WORDS = ["接口", "调试", "响应", "字段", "分页", "缓存", "重试", "鉴权", "限流", "日志"]
_TLD = ["com", "dev", "io", "cn", "app"]

PH_RE = re.compile(r"\{\{\s*@([a-zA-Z_]+)\s*(?:\(\s*([^)]*)\))?\s*\}\}")


def _rng() -> random.Random:
    """每个请求一个随机源：同一份响应体里多次出现 {{@id}} 会得到不同的值。"""
    return random.Random()


def _num(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _gen(kind: str, arg: str, rnd: random.Random) -> str:
    """生成一个占位符的值。返回字符串，由调用方决定加不加引号。"""
    parts = [p.strip() for p in (arg or "").split(",")] if arg else []
    k = (kind or "").lower()
    if k in ("name", "fullname"):
        return f"{rnd.choice(_FIRST)} {rnd.choice(_LAST)}"
    if k in ("firstname", "givenname"):
        return rnd.choice(_FIRST)
    if k in ("lastname", "surname"):
        return rnd.choice(_LAST)
    if k in ("cname", "zhname", "chinese"):
        return f"{rnd.choice(_CN_LAST)}{rnd.choice(_CN_FIRST)}{rnd.choice(_CN_FIRST)}"
    if k == "email":
        return f"{rnd.choice(_FIRST).lower()}.{rnd.randint(1, 999)}@{rnd.choice(_COMPANY).split()[0].lower()}.{rnd.choice(_TLD)}"
    if k in ("phone", "mobile"):
        return f"1{rnd.choice('3456789')}{rnd.randint(100000000, 999999999)}"
    if k == "city":
        return rnd.choice(_CITY)
    if k == "company":
        return rnd.choice(_COMPANY)
    if k in ("id", "uid"):
        lo = int(_num(parts[0], 1)) if parts else 1
        hi = int(_num(parts[1], 99999)) if len(parts) > 1 else 99999
        return str(rnd.randint(min(lo, hi), max(lo, hi)))
    if k == "uuid":
        return str(_uuid.uuid4())
    if k in ("int", "integer", "number"):
        lo = int(_num(parts[0], 0)) if parts else 0
        hi = int(_num(parts[1], 100)) if len(parts) > 1 else 100
        return str(rnd.randint(min(lo, hi), max(lo, hi)))
    if k in ("float", "double", "price"):
        lo = _num(parts[0], 0) if parts else 0
        hi = _num(parts[1], 100) if len(parts) > 1 else 100
        lo, hi = min(lo, hi), max(lo, hi)
        return f"{rnd.uniform(lo, hi):.2f}"
    if k in ("bool", "boolean"):
        return "true" if rnd.random() < 0.5 else "false"
    if k in ("now", "datetime", "time"):
        return time.strftime("%Y-%m-%d %H:%M:%S")
    if k in ("date", "today"):
        return time.strftime("%Y-%m-%d")
    if k in ("timestamp", "ts"):
        return str(int(time.time() * 1000))
    if k in ("words", "lorem", "sentence"):
        n = int(_num(parts[0], 6)) if parts else 6
        n = max(1, min(n, 40))
        return "".join(rnd.choice(_WORDS) for _ in range(n)) + "。"
    if k in ("url", "link"):
        name = rnd.choice(_WORDS).encode("utf-8").hex()[:6]
        return f"https://{rnd.choice(_COMPANY).split()[0].lower()}.{rnd.choice(_TLD)}/{name}"
    if k in ("avatar", "image", "img"):
        w = int(_num(parts[0], 200)) if parts else 200
        h = int(_num(parts[1], w)) if len(parts) > 1 else w
        w, h = max(16, min(w, 2000)), max(16, min(h, 2000))
        return f"https://picsum.photos/seed/{rnd.randint(1, 9999)}/{w}/{h}"
    if k in ("pick", "oneof", "enum"):
        pool = [p for p in parts if p] or ["a", "b", "c"]
        return rnd.choice(pool)
    if k in ("seq", "index"):
        return str(rnd.randint(1, 1000))
    return f"{{{{@{kind}}}}}"


def render_placeholders(text: str) -> str:
    """把 {{@xxx}} 换成现算的值；不认识的占位符原样留着，方便发现拼写错误。"""
    if not text or "{{" not in text:
        return text or ""
    rnd = _rng()

    def repl(m: "re.Match[str]") -> str:
        return _gen(m.group(1), m.group(2) or "", rnd)

    return PH_RE.sub(repl, text)


# ---------------------------------------------------------------- 路由定义


def route(name: str, method: str = "GET", path: str = "/api/hello", status: int = 200,
          body: str = ECHO_JSON, content_type: str = "application/json",
          delay: int = 0, echo: bool = False, enabled: bool = True,
          rules: Optional[List[Dict[str, Any]]] = None,
          group: str = "") -> Dict[str, Any]:
    return {
        "id": f"m{int(time.time() * 1000) % 10 ** 9}{len(name)}",
        "name": name, "group": group or "", "method": method.upper(),
        "path": path if path.startswith("/") else
        "/" + path, "status": int(status), "content_type": content_type,
        "body": body, "delay": int(delay), "echo": bool(echo), "enabled": bool(enabled),
        "rules": list(rules or []),
    }


def local_ips() -> List[str]:
    """本机在局域网里的 IPv4 地址（用来生成二维码 / 展示可访问地址）。

    先连一个外部地址拿到出口 IP（UDP connect 不会真的发包），再补上主机名解析
    出来的其它网卡地址；都拿不到就返回空列表，界面只显示 localhost。
    """
    ips: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            ips.append(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def rule(source: str = "header", key: str = "token", op: str = "eq", value: str = "",
         status: int = 200, delay: int = 0, body: str = "", name: str = "") -> Dict[str, Any]:
    """一条条件规则：请求命中 source/key/op/value 时，用这里的响应覆盖默认响应。"""
    return {"id": "r" + _uuid.uuid4().hex[:6], "name": name or f"{key} {op} {value}".strip(),
            "source": source, "key": key, "op": op, "value": value,
            "status": int(status), "delay": int(delay), "body": body}


def default_routes() -> List[Dict[str, Any]]:
    """首次打开时的几条示例：动态数据、鉴权规则、回显、延迟、错误码。"""
    return [
        route("用户信息（动态）", "GET", "/api/user", 200, PROFILE_JSON, group="示例/用户"),
        route("鉴权规则", "GET", "/api/profile", 401,
              json.dumps({"code": 401, "message": "缺少 token"}, ensure_ascii=False, indent=2),
              rules=[rule("header", "token", "eq", "123", 200, 0, AUTH_RULE_BODY,
                          "带 token=123 返回 VIP 数据")], group="示例/用户"),
        route("回显请求", "POST", "/api/echo", 200, "", echo=True, group="示例/调试"),
        route("慢接口 2s", "GET", "/api/slow", 200,
              json.dumps({"ok": True, "note": "延迟 2 秒返回，用来测 Loading 与超时"},
                         ensure_ascii=False, indent=2), delay=2000, group="示例/调试"),
        route("服务异常", "GET", "/api/boom", 500,
              json.dumps({"error": "internal_error", "message": "手动制造的 500"},
                         ensure_ascii=False, indent=2), group="示例/调试"),
    ]


def mock_config(data: Dict[str, Any]) -> Dict[str, Any]:
    """把 store.data["mock"] 归一化成「多实例 + 旧字段兼容」的形状。

    - 老版本只有 port / routes / auto_start：迁移成一个 id=main 的实例；
    - 新版本每个实例各自有 routes / port / lan，互不影响；
    - `cfg["routes"]` / `cfg["port"]` 仍然指向第一个实例，旧代码不用改。
    """
    cfg = data.setdefault("mock", {})
    cfg.setdefault("fallback_echo", False)
    cfg.setdefault("auto_start", False)
    if not cfg.get("instances"):
        legacy = cfg.get("routes") or default_routes()
        for r in legacy:
            if not r.get("id"):
                r["id"] = "m" + _uuid.uuid4().hex[:8]
            if not r.get("group") and str(r.get("name") or "").startswith("示例"):
                r["group"] = "示例"
            r.setdefault("group", "")
            r.setdefault("enabled", True)
            r.setdefault("rules", [])
        cfg["instances"] = [{
            "id": "main",
            "name": "默认实例",
            "port": int(cfg.get("port") or DEFAULT_PORT),
            "lan": False,
            "auto_start": bool(cfg.get("auto_start", False)),
            "routes": legacy,
        }]
    for inst in cfg["instances"]:
        inst.setdefault("id", "main")
        inst.setdefault("name", inst["id"])
        inst.setdefault("port", DEFAULT_PORT)
        inst.setdefault("lan", False)
        inst.setdefault("auto_start", cfg.get("auto_start", False))
        inst.setdefault("routes", [])
        for r in inst["routes"]:
            if not r.get("id"):
                r["id"] = "m" + _uuid.uuid4().hex[:8]
            r.setdefault("group", "")
            r.setdefault("enabled", True)
            r.setdefault("rules", [])
    cfg["port"] = cfg["instances"][0].get("port", DEFAULT_PORT)
    cfg["routes"] = cfg["instances"][0].get("routes", [])
    return cfg


def _match(table: Dict[Tuple[str, str], Dict[str, Any]], method: str,
           path: str) -> Optional[Dict[str, Any]]:
    hit = table.get((method, path))
    if hit is not None:
        return hit
    hit = table.get(("*", path))          # 方法通配
    if hit is not None:
        return hit
    # 前缀通配：/api/users/* 命中 /api/users/42?x=1
    for (m, p), item in table.items():
        if p.endswith("*") and (m == method or m == "*") and path.startswith(p[:-1]):
            return item
    return None


def _ops(op: str, given: str, want: str) -> bool:
    o = (op or "eq").lower()
    g, w = given or "", want or ""
    if o in ("exists", "present"):
        return bool(g)
    if o in ("missing", "absent"):
        return not g
    if o in ("contains", "has"):
        return w.lower() in g.lower()
    if o in ("regex", "matches"):
        try:
            return re.search(w, g) is not None
        except re.error:
            return False
    if o in ("startswith", "prefix"):
        return g.lower().startswith(w.lower())
    if o in ("gt", "lt"):
        try:
            a, b = float(g), float(w)
        except (TypeError, ValueError):
            return False
        return a > b if o == "gt" else a < b
    return g.strip().lower() == w.strip().lower()


class _MockHTTPServer(ThreadingHTTPServer):
    """记着还开着的连接，停服务时连同 keep-alive 的老连接一起掐断。

    ThreadingHTTPServer 每个连接起一个线程，HTTP/1.1 的 keep-alive 会让这个线程
    一直循环等下一个请求。`server_close()` 只关监听套接字，已经建立的连接照样能继续
    收发 —— 这就是「面板显示已停止、浏览器刷新还能拿到数据」的真正原因。
    """

    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conns = set()
        self._conn_lock = threading.Lock()

    def process_request(self, request, client_address):   # noqa: D102
        with self._conn_lock:
            self._conns.add(request)
        super().process_request(request, client_address)

    def close_request(self, request):                     # noqa: D102
        with self._conn_lock:
            self._conns.discard(request)
        super().close_request(request)

    def drop_connections(self) -> None:
        """把所有活着的连接立刻断掉（不给它再回一个响应）。"""
        with self._conn_lock:
            conns = list(self._conns)
            self._conns.clear()
        for conn in conns:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Ocelot-Mock"
    sys_version = ""

    # ---- 工具
    def log_message(self, *_args):       # 不往终端刷日志
        pass

    def _send(self, status: int, body: bytes, content_type: str,
              extra: Optional[Dict[str, str]] = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type or "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Access-Control-Expose-Headers", "*")
            self.send_header("Access-Control-Allow-Methods",
                             "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Ocelot-Mock", "1")
            # 不复用连接：Mock 是一次性的调试工具，keep-alive 只会让「停服务」变不干净
            self.send_header("Connection", "close")
            self.close_connection = True
            for k, v in (extra or {}).items():
                self.send_header(str(k), _header_safe(str(v)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, payload: Any, extra: Optional[Dict[str, str]] = None) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                   "application/json; charset=utf-8", extra)

    # ---- 入口
    def _handle(self) -> None:
        started = time.perf_counter()
        try:
            self._route(started)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:      # noqa: BLE001 — 一条路由写错不该让服务挂掉
            try:
                self._json(500, {"error": "mock_internal", "message": str(exc)})
            except Exception:         # noqa: BLE001
                pass

    def _read_body(self) -> str:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if not length:
            return ""
        raw = self.rfile.read(min(length, 2_000_000))
        try:
            return raw.decode("utf-8", "replace")
        except Exception:             # noqa: BLE001
            return ""

    def _route(self, started: float) -> None:
        mock = getattr(self.server, "ocelot", None)
        split = urlsplit(self.path)
        raw_path = split.path or "/"

        if raw_path == PING_PATH:     # 用来判断「这个端口上是不是另一个 Ocelot」
            self._json(200, {"app": "ocelot", "mock": True,
                             "routes": len(getattr(mock, "table", {}) or {})})
            return

        if self.command == "OPTIONS":       # 预检：浏览器里跨域调试直接能用
            self._send(204, b"", "text/plain")
            return

        table = getattr(mock, "table", {}) if mock else {}
        item = _match(table, self.command, raw_path)
        body_text = self._read_body() if self.command in ("POST", "PUT", "PATCH", "DELETE") else ""
        query = {k: v[0] if v else "" for k, v in
                 parse_qs(split.query, keep_blank_values=True).items()}
        headers = {k.lower(): v for k, v in self.headers.items()}

        extra = {
            "client": (self.client_address[0] if self.client_address else ""),
            "query": split.query,
            "ctype": headers.get("content-type", ""),
        }

        if item is None and mock is not None and getattr(mock, "fallback_echo", False):
            status = 200
            payload = {"note": "没有匹配的规则，已回显请求", "method": self.command,
                       "path": self.path, "body": body_text}
            self._json(status, payload)
            mock.log(self.command, self.path, status, started, "回显兜底",
                     size=len(json.dumps(payload, ensure_ascii=False).encode("utf-8")), **extra)
            return
        if item is None:
            status = 404
            self._json(status, {
                "error": "no_mock_route",
                "message": i18n.trf("没有找到 {method} {path} 的 Mock 规则",
                                    method=self.command, path=raw_path),
                "hint": i18n.tr("在 Ocelot「Mock 服务」里新建一条，"
                                "或把路径写成 /api/users/* 做前缀匹配"),
                "routes": sorted(f"{m} {p}" for (m, p) in table),
            })
            if mock is not None:
                mock.log(self.command, self.path, status, started, "未匹配",
                         size=len(body_text.encode("utf-8")), **extra)
            return

        # ---- 条件规则：第一条命中的覆盖默认响应
        hit_rule = None
        for r in item.get("rules") or []:
            src = (r.get("source") or "header").lower()
            key = r.get("key") or ""
            if src == "header":
                given = headers.get(key.lower(), "")
            elif src == "query":
                given = query.get(key, "")
            elif src == "body":
                given = body_text if not key else _dig(body_text, key)
            elif src == "method":
                given = self.command
                key = ""
            elif src == "path":
                given = raw_path
                key = ""
            else:
                given = ""
            if _ops(r.get("op") or "eq", given, r.get("value") or ""):
                hit_rule = r
                break

        source = hit_rule or item
        delay = int(source.get("delay") or 0)
        if delay:
            time.sleep(min(max(delay, 0), 30_000) / 1000)
        status = int(source.get("status") or 200)

        if item.get("echo") and hit_rule is None:
            self._json(status, {
                "method": self.command,
                "path": self.path,
                "query": query,
                "headers": headers,
                "body": body_text,
                "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            if mock is not None:
                mock.log(self.command, self.path, status, started, item.get("name") or "回显",
                         size=len(body_text.encode("utf-8")), **extra)
            return

        text = source.get("body") or ""
        if hit_rule is not None and not text:
            text = item.get("body") or ""
        text = render_placeholders(text)
        ctype = item.get("content_type") or "application/json; charset=utf-8"
        self._send(status, text.encode("utf-8"), ctype,
                   {"X-Ocelot-Route": item.get("name") or "",
                    "X-Ocelot-Rule": (hit_rule or {}).get("name") or ""})
        if mock is not None:
            mock.log(self.command, self.path, status, started, item.get("name") or "路由",
                     (hit_rule or {}).get("name") or "",
                     size=len(text.encode("utf-8")), **extra)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_PATCH = _handle
    do_DELETE = _handle
    do_HEAD = _handle
    do_OPTIONS = _handle


def _header_safe(value: str) -> str:
    """HTTP 头只能是 latin-1：路由名里有中文时按 URL 编码塞进去，不能让它把响应打崩。"""
    try:
        value.encode("latin-1")
        return value
    except UnicodeEncodeError:
        from urllib.parse import quote

        return quote(value, safe="")


def _dig(text: str, key: str) -> str:
    """从 JSON 请求体里取一个字段（支持 a.b.c），取不到就当空串。"""
    if not text.strip():
        return ""
    try:
        data = json.loads(text)
    except Exception:      # noqa: BLE001 —— 非 JSON 就按原文找
        return text if key in text else ""
    cur: Any = data
    for part in str(key).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, "")
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
    if isinstance(cur, (dict, list)):
        return json.dumps(cur, ensure_ascii=False)
    return "" if cur is None else str(cur)


class MockServer:
    """一个 Mock 服务实例。

    一个进程可以有多个实例（MockHub 管着）：调试「订单服务 + 商品服务」这种
    互相调用的场景时，8787 / 8788 各起一个，比来回改端口省事得多。
    """

    def __init__(self, instance: str = "main", name: str = "") -> None:
        self.instance = instance or "main"
        self.name = name or self.instance
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port = 0
        self.host = "127.0.0.1"
        self.table: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.routes: List[Dict[str, Any]] = []
        self.fallback_echo = False
        self.hits: Dict[str, int] = {}
        self.duplicates = 0
        self.logs: Deque[Dict[str, Any]] = deque(maxlen=LOG_LIMIT)
        self._lock = threading.Lock()

    # -------------------------------------------------- 状态
    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def lan(self) -> bool:
        return self.host == "0.0.0.0"

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def lan_urls(self) -> List[str]:
        """局域网里其它设备可用的地址；没开局域网监听时返回空列表。"""
        if not self.lan or not self.port:
            return []
        return [f"http://{ip}:{self.port}" for ip in local_ips()]

    def urls(self) -> List[str]:
        return [self.base] + self.lan_urls()

    @property
    def requests(self) -> int:
        with self._lock:
            return len(self.logs)

    def url_for(self, path: str, lan: bool = False) -> str:
        p = path if path.startswith("/") else "/" + str(path)
        if lan:
            nets = self.lan_urls()
            if nets:
                return nets[0] + p
        return self.base + p

    def log(self, method: str, path: str, status: int, started: float, route_name: str,
            rule_name: str = "", client: str = "", query: str = "", size: int = 0,
            ctype: str = "") -> None:
        """记一条请求日志；`hits` 按路由名统计命中次数，面板里显示「×N」。"""
        item = {
            "time": time.strftime("%H:%M:%S"),
            "method": method,
            "path": unquote_plus(path),
            "status": int(status),
            "ms": int((time.perf_counter() - started) * 1000),
            "route": route_name,
            "rule": rule_name,
            "client": client or "",
            "query": query or "",
            "size": int(size or 0),
            "ctype": (ctype or "").split(";")[0],
            "instance": self.instance,
        }
        with self._lock:
            self.logs.appendleft(item)
            if route_name and route_name not in ("未匹配", "回显兜底"):
                self.hits[route_name] = self.hits.get(route_name, 0) + 1

    def clear_logs(self) -> None:
        with self._lock:
            self.logs.clear()
            self.hits.clear()

    # -------------------------------------------------- 启停
    def start(self, routes: List[Dict[str, Any]], port: int = DEFAULT_PORT,
              fallback_echo: bool = False, lan: bool = False) -> Tuple[bool, str]:
        self.stop()
        self.host = "0.0.0.0" if lan else "127.0.0.1"
        self.routes = []
        for r in routes or []:
            item = dict(r)
            body = item.get("body")
            if body is not None and not isinstance(body, str):
                # 手写 state.json 时 body 可能直接写成对象，顺手转成字符串
                try:
                    item["body"] = json.dumps(body, ensure_ascii=False, indent=2)
                except Exception:     # noqa: BLE001
                    item["body"] = str(body)
            item["rules"] = [dict(x) for x in (item.get("rules") or [])]
            self.routes.append(item)
        self.table = {}
        dup = 0
        for r in self.routes:
            if not r.get("enabled", True):
                continue
            key = (str(r.get("method") or "GET").upper(), str(r.get("path") or "/"))
            if key in self.table:
                dup += 1
            self.table[key] = r
        self.duplicates = dup
        self.fallback_echo = bool(fallback_echo)
        with self._lock:
            self.hits = {}
        if not self.table:
            return False, "还没有启用的路由"
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = DEFAULT_PORT

        note = ""
        if getattr(self, "duplicates", 0):
            note = i18n.trf("有 {n} 条路由方法 + 路径重复，只保留了后面的那条",
                            n=self.duplicates)
        try:
            httpd = _MockHTTPServer((self.host, max(0, port)), _Handler)
        except OSError as exc:
            if not port:
                return False, i18n.trf("启动失败：{err}", err=exc)
            # 端口被别人的进程占着。如果对方也是 Ocelot，说明另一个实例在跑 ——
            # 这时候最忌「默默换端口」，用户会以为 8787 是自己这个服务。
            other = self._probe_ocelot(port)
            try:
                httpd = _MockHTTPServer((self.host, 0), _Handler)
            except OSError:
                return False, i18n.trf("启动失败：{err}", err=exc)
            if other:
                note = i18n.trf("端口 {port} 已被另一个 Ocelot Mock 服务占用，本次改用 {alt}",
                                port=port, alt=httpd.server_address[1])
            else:
                note = i18n.trf("端口 {port} 已被其它程序占用，本次改用 {alt}",
                                port=port, alt=httpd.server_address[1])
        httpd.daemon_threads = True
        httpd.ocelot = self            # type: ignore[attr-defined]
        self._httpd = httpd
        self.port = httpd.server_address[1]
        self._thread = threading.Thread(target=self._serve, name="ocelot-mock", daemon=True)
        self._thread.start()
        if not note and self.lan:
            nets = self.lan_urls()
            if nets:
                note = i18n.trf("已启动 · {url}（局域网 {lan}）", url=self.base, lan=nets[0])
        return True, note or i18n.trf("已启动 · {url}", url=self.base)

    @staticmethod
    def _probe_ocelot(port: int, timeout: float = 0.6) -> bool:
        """问一句「你是不是 Ocelot」：只连本机，失败就当普通占用处理。"""
        import http.client

        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            conn.request("GET", PING_PATH)
            resp = conn.getresponse()
            ok = resp.status == 200 and b"ocelot" in resp.read(200).lower()
            conn.close()
            return ok
        except Exception:      # noqa: BLE001
            return False

    def _serve(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        try:
            httpd.serve_forever(poll_interval=0.15)
        except Exception:       # noqa: BLE001 — 线程里出错不能带崩应用
            pass

    def stop(self) -> None:
        httpd, thread = self._httpd, self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:       # noqa: BLE001
                pass
            # 先掐断所有活着的连接，再关监听口：只关监听口的话，浏览器那条
            # keep-alive 老连接还能继续拿到响应（「已停止但刷新照样能看」就是这么来的）
            try:
                httpd.drop_connections()
            except Exception:       # noqa: BLE001
                pass
            try:
                httpd.server_close()
            except Exception:       # noqa: BLE001
                pass
        if thread is not None and thread.is_alive():
            thread.join(1.2)
        # 端口释放是异步的：不等它真的关掉就把 self.port 清掉，界面会显示「已停止」
        # 但浏览器还能连上（我们之前就是这样被自己的影子服务骗过）。
        port = self.port
        if port:
            for _ in range(40):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.12):
                        pass
                except OSError:
                    break
                time.sleep(0.025)
        self.port = 0

    # -------------------------------------------------- 调试
    def probe(self, timeout: float = 0.8) -> bool:
        """自检：真的连一下自己，确认服务可用。"""
        if not self.running or not self.port:
            return False
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=timeout):
                return True
        except OSError:
            return False

    def port_in_use(self, port: int) -> bool:
        """端口是否被占（不看是不是自己）。面板用它提示「换个端口」。"""
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
                return True
        except OSError:
            return False


class MockHub:
    """一组 MockServer：多实例启动时，「订单服务」「商品服务」各占一个端口。

    UI 只和 Hub 打交道：按实例 id 取 server、统一看谁在跑、关窗时统一收掉。
    """

    def __init__(self) -> None:
        self._servers: Dict[str, MockServer] = {}

    def get(self, instance: str = "main", name: str = "") -> MockServer:
        srv = self._servers.get(instance)
        if srv is None:
            srv = MockServer(instance, name)
            self._servers[instance] = srv
        elif name:
            srv.name = name
        return srv

    def attach(self, srv: MockServer) -> MockServer:
        """把一个已存在的 server 挂进来（兼容只传单个实例的旧调用方）。"""
        self._servers[srv.instance or "main"] = srv
        return srv

    def all(self) -> List[MockServer]:
        return list(self._servers.values())

    def running(self) -> List[MockServer]:
        return [s for s in self._servers.values() if s.running]

    @property
    def primary(self) -> MockServer:
        return self.get("main")

    @property
    def is_running(self) -> bool:
        return bool(self.running())

    @property
    def base(self) -> str:
        srv = self._servers.get("main")
        if srv is not None and srv.running:
            return srv.base
        for s in self._servers.values():
            if s.running:
                return s.base
        return f"http://127.0.0.1:{DEFAULT_PORT}"

    @property
    def logs(self) -> List[Dict[str, Any]]:
        """所有实例的日志合并，按时间倒序 —— 日志页要能一眼看全。"""
        out: List[Dict[str, Any]] = []
        for srv in self._servers.values():
            out.extend(list(srv.logs))
        out.sort(key=lambda e: e.get("time") or "", reverse=True)
        return out

    def clear_logs(self) -> None:
        for srv in self._servers.values():
            srv.clear_logs()

    def stop_all(self) -> None:
        for srv in self._servers.values():
            try:
                srv.stop()
            except Exception:      # noqa: BLE001
                pass
