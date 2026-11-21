"""集合的导入 / 导出：与主流 API 工具互通。

支持的格式
----------
导入：Ocelot JSON、Postman v2.0/v2.1、Apifox、Hoppscotch、Insomnia v4、OpenAPI 3.x、HAR
导出：Ocelot JSON（Postman v2.1 兼容的超集，别的工具也能直接吃）、Postman v2.1、
      OpenAPI 3.1（JSON / YAML）、HAR

设计要点
--------
* 导出优先用 Postman v2.1 的结构（info + item + event + auth），这是事实标准：
  Postman / Apifox / Insomnia / Hoppscotch 都能直接导入。我们额外塞一个
  ``x-ocelot`` 键保存脚本、Inherit 认证、Cookies 等对方没有的概念，
  导回来时再原样还原 —— 既通用又不丢信息。
* 导入一律「尽力而为」：字段缺失就补默认值，绝不因为某个请求不合法就整份失败。
* 所有转换都是纯函数，方便自测。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .store import kv, new_folder, new_request, uid

POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

# 导入时可识别的来源（对话框里按这个顺序列出来）
IMPORT_SOURCES = [
    ("ocelot", "从 Ocelot JSON 导入", "Ocelot / Postman v2.1 兼容格式，保留脚本与认证"),
    ("postman", "从 Postman 导入", "Collection v2.0 / v2.1 导出的 JSON"),
    ("apifox", "从 Apifox 导入", "Apifox 导出的 JSON（Postman 兼容）"),
    ("hoppscotch", "从 Hoppscotch 导入", "Hoppscotch 集合导出的 JSON"),
    ("insomnia", "从 Insomnia 导入", "Insomnia 导出的 JSON（v4）"),
    ("openapi", "从 OpenAPI 导入", "OpenAPI 3.x / Swagger 2.0，JSON 或 YAML"),
    ("har", "从 HAR 导入", "浏览器开发者工具导出的 .har"),
]

EXPORT_TARGETS = [
    ("ocelot", "导出为 Ocelot JSON", "Postman v2.1 兼容，附 x-ocelot 元数据；保留脚本、认证、环境变量"),
    ("postman", "导出为 Postman v2.1", "最通用的集合格式，Postman / Apifox 可直接导入"),
    ("openapi-json", "导出为 OpenAPI 3.1 (JSON)", "接口文档格式，只保留路径、方法、参数与示例"),
    ("openapi-yaml", "导出为 OpenAPI 3.1 (YAML)", "同上，YAML 写法，适合放进代码仓库"),
    ("har", "导出为 HAR", "抓包归档格式，适合给同事复现问题"),
]

EXT = {"ocelot": ".json", "postman": ".json", "openapi-json": ".json",
       "openapi-yaml": ".yaml", "har": ".har"}

# 展示用名字（导入成功后告诉用户「这次认成了什么」）
FORMAT_LABELS = {
    "ocelot": "Ocelot JSON",
    "postman": "Postman v2.0 / v2.1",
    "postman_dump": "Postman 数据包",
    "postman_v1": "Postman v1",
    "apifox": "Apifox",
    "hoppscotch": "Hoppscotch",
    "insomnia": "Insomnia v4",
    "openapi": "OpenAPI / Swagger",
    "har": "HAR",
    "native": "Ocelot 集合",
}


# ---------------------------------------------------------------- 公共小工具

def _slug(text: str, fallback: str = "request") -> str:
    s = re.sub(r"[^\w\-\u4e00-\u9fa5]+", "-", (text or "").strip()).strip("-")
    return s or fallback


def _request_url(req: Dict[str, Any]) -> str:
    return str(req.get("url") or "").strip()


def _merge_query(url: str, params: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """把 base URL 与参数表拆开：返回 (不带查询串的地址, 参数列表)。"""
    base, _, query = (url or "").partition("?")
    rows: List[Dict[str, Any]] = []
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        rows.append({"key": key, "value": value, "enabled": True})
    for p in params or []:
        if isinstance(p, dict) and (p.get("key") or ""):
            rows.append({"key": str(p["key"]), "value": str(p.get("value", "")),
                         "enabled": bool(p.get("enabled", True))})
    return base, rows


# ---------------------------------------------------------------- 导出：Postman / Ocelot

def _postman_body(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mode = (body or {}).get("mode") or "none"
    raw = (body or {}).get("raw") or ""
    if mode == "none" or (not raw and not (body or {}).get("form") and not (body or {}).get("file")):
        return None
    if mode in ("json", "xml", "text", "raw"):
        lang = "json" if mode == "json" else (
            "xml" if mode == "xml" else (body.get("raw_lang") or "text"))
        if lang == "text":
            lang = "text"
        return {"mode": "raw", "raw": raw,
                "options": {"raw": {"language": lang}}}
    if mode in ("form", "urlencoded"):
        key = "formdata" if mode == "form" else "urlencoded"
        rows = []
        for row in body.get("form") or []:
            kind = str(row.get("type") or "text").lower()
            item = {"key": str(row.get("key") or ""), "type": "text",
                    "value": str(row.get("value") or ""),
                    "disabled": not bool(row.get("enabled", True))}
            if kind == "file" or (row.get("value") or "").startswith("@"):
                item["type"] = "file"
                item["src"] = str(row.get("value") or "").lstrip("@")
                item.pop("value", None)
            rows.append(item)
        return {"mode": key, key: rows}
    if mode == "binary":
        return {"mode": "file", "file": {"src": body.get("file") or ""}}
    return None


def _postman_auth(auth: Dict[str, Any], carry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    kind = (auth or {}).get("type") or "none"
    if kind == "bearer":
        return {"type": "bearer", "bearer": [{"key": "token", "value": auth.get("token", ""),
                                             "type": "string"}]}
    if kind == "basic":
        return {"type": "basic", "basic": [
            {"key": "username", "value": auth.get("username", ""), "type": "string"},
            {"key": "password", "value": auth.get("password", ""), "type": "string"}]}
    if kind == "apikey":
        return {"type": "apikey", "apikey": [
            {"key": "key", "value": auth.get("key", ""), "type": "string"},
            {"key": "value", "value": auth.get("value", ""), "type": "string"},
            {"key": "in", "value": auth.get("add_to") or "header", "type": "string"}]}
    if kind == "oauth2":
        fields = []
        for key in ("client_id", "client_secret", "access_token", "refresh_token",
                    "token_url", "auth_url", "scope", "username", "password",
                    "issuer", "state", "token_auth_method"):
            val = auth.get("oauth_" + key) or ""
            if val:
                fields.append({"key": key, "value": str(val), "type": "string"})
        return {"type": "oauth2", "oauth2": fields}
    if kind == "awsv4":
        return {"type": "awsv4", "awsv4": [
            {"key": "accessKey", "value": auth.get("aws_access_key_id", ""), "type": "string"},
            {"key": "secretKey", "value": auth.get("aws_secret_access_key", ""), "type": "string"},
            {"key": "sessionToken", "value": auth.get("aws_session_token", ""), "type": "string"},
            {"key": "region", "value": auth.get("aws_region", ""), "type": "string"},
            {"key": "service", "value": auth.get("aws_service", ""), "type": "string"},
        ]}
    if kind == "digest":
        return {"type": "digest", "digest": [
            {"key": "username", "value": auth.get("digest_username", ""), "type": "string"},
            {"key": "password", "value": auth.get("digest_password", ""), "type": "string"},
            {"key": "realm", "value": auth.get("digest_realm", ""), "type": "string"},
            {"key": "nonce", "value": auth.get("digest_nonce", ""), "type": "string"},
            {"key": "algorithm", "value": auth.get("digest_algorithm", "MD5"), "type": "string"},
            {"key": "qop", "value": auth.get("digest_qop", "auto"), "type": "string"},
            {"key": "opaque", "value": auth.get("digest_opaque", ""), "type": "string"},
        ]}
    if kind in ("jwt", "inherit"):
        # Postman 没有这两种，放进 x-ocelot 里由我们自己还原
        carry["auth"] = dict(auth)
    return None


def _postman_item(req: Dict[str, Any]) -> Dict[str, Any]:
    base, query = _merge_query(_request_url(req), req.get("params") or [])
    url: Dict[str, Any] = {"raw": _request_url(req) or base, "query": [
        {"key": q["key"], "value": q["value"], "disabled": not q["enabled"]} for q in query]}
    item: Dict[str, Any] = {
        "name": req.get("name") or "Untitled Request",
        "request": {
            "method": (req.get("method") or "GET").upper(),
            "header": [{"key": str(h.get("key") or ""), "value": str(h.get("value") or ""),
                        "type": "text", "disabled": not bool(h.get("enabled", True))}
                       for h in req.get("headers") or [] if h.get("key")],
            "url": url,
        },
    }
    if not query:
        item["request"]["url"] = {"raw": base or "/"}
    body = _postman_body(req.get("body") or {})
    if body:
        item["request"]["body"] = body
    carry: Dict[str, Any] = {}
    auth = _postman_auth(req.get("auth") or {}, carry)
    if auth:
        item["request"]["auth"] = auth
    events = []
    scripts = req.get("scripts") or {}
    if (scripts.get("pre") or "").strip():
        events.append({"listen": "prerequest",
                       "script": {"type": "text/javascript",
                                  "exec": scripts["pre"].splitlines() or [""]}})
    if (scripts.get("post") or "").strip():
        events.append({"listen": "test",
                       "script": {"type": "text/javascript",
                                  "exec": scripts["post"].splitlines() or [""]}})
    if events:
        item["event"] = events
    extra: Dict[str, Any] = {}
    # Postman 只认 JavaScript 事件；Python 脚本与当前语言放进 x-ocelot，
    # 导回来还是原来那份，不会被悄悄改成 JS。
    if any(scripts.get(k) for k in ("pre_python", "post_python", "pre_lang", "post_lang")):
        extra["scripts"] = dict(scripts)
    if req.get("cookies"):
        extra["cookies"] = req["cookies"]
    if req.get("note"):
        item["request"]["description"] = req["note"]
    # WebSocket：方法本身是 WS，常用消息 / 子协议 / 心跳存在 x-ocelot 里，
    # 导回来还是原来的连接配置（别的工具会当成一个自定义方法的请求，不会报错）
    # 只看方法：以前还看 req.get("ws")，但编辑器会给每个请求补一份 ws 默认值，
    # 结果普通 HTTP 请求导出后也被当成 WebSocket（导回来方法就变成 WS 了）。
    if (req.get("method") or "").upper() == "WS":
        extra["ws"] = req.get("ws") or {}
    # SSE：方法 + 连接选项（自动重连 / Last-Event-ID）。别的工具读不懂时
    # 也只是一个自定义方法的普通请求，不会报错。
    if (req.get("method") or "").upper() == "SSE" or req.get("sse"):
        extra["sse"] = req.get("sse") or {}
    if carry:
        extra.update(carry)
    if extra:
        item["x-ocelot"] = extra
    return item


def _postman_folder(node: Dict[str, Any]) -> Dict[str, Any]:
    item = {"name": node.get("name") or "Folder",
            "item": [_postman_node(child) for child in node.get("children") or []]}
    if node.get("auth") and (node.get("auth") or {}).get("type") not in (None, "none"):
        item["x-ocelot"] = {"folderAuth": node["auth"]}
    return item


def _postman_node(node: Dict[str, Any]) -> Dict[str, Any]:
    if node.get("type") == "folder":
        return _postman_folder(node)
    return _postman_item(node)


def _export_nodes(store, nodes=None) -> List[Dict[str, Any]]:
    """导出范围：默认整个集合树；从文件夹右键导出时只传这个文件夹。"""
    if nodes is None:
        return list(store.collections)
    return list(nodes)


def to_postman(store, name: str = "Ocelot Collection", extra: bool = False,
               nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "info": {"name": name, "_postman_id": uid(), "schema": POSTMAN_SCHEMA},
        "item": [_postman_node(n) for n in _export_nodes(store, nodes)],
    }
    if extra:
        data["x-ocelot"] = {
            "version": 1,
            "generator": "Ocelot",
            "environments": store.environments,
            "active_env": store.data.get("active_env"),
        }
    return data


def to_ocelot(store, name: str = "Ocelot Collection",
              nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Ocelot JSON = Postman v2.1 + x-ocelot 元数据。

    刻意不用私有结构：Postman / Apifox / Insomnia 都能直接导入这份文件，
    我们自己导回来也不丢脚本、认证、Cookie。
    """
    return to_postman(store, name, extra=True, nodes=nodes)


# ---------------------------------------------------------------- 导出：OpenAPI

_OPENAPI_HINT = re.compile(r"^\{\{([^{}]+)\}\}")


def _split_server(url: str) -> Tuple[str, str]:
    m = _OPENAPI_HINT.match(url or "")
    if m:
        return "{{" + m.group(1) + "}}", (url or "")[m.end():] or "/"
    m = re.match(r"^(https?://[^/]+)(/.*)?$", url or "")
    if m:
        return m.group(1), m.group(2) or "/"
    return "https://example.com", "/" + (url or "").lstrip("/")


def to_openapi(store, name: str = "Ocelot API",
               nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    servers: List[str] = []
    paths: Dict[str, Dict[str, Any]] = {}

    def walk(nodes: List[Dict[str, Any]], folder_auth: Optional[Dict[str, Any]] = None):
        for node in nodes:
            if node.get("type") == "folder":
                walk(node.get("children") or [], node.get("auth") or folder_auth)
                continue
            server, path = _split_server(_request_url(node))
            if server not in servers:
                servers.append(server)
            params = []
            for p in node.get("params") or []:
                if not (p.get("key") or ""):
                    continue
                params.append({"name": str(p["key"]), "in": "query", "required": False,
                               "schema": {"type": "string", "default": str(p.get("value") or "")}})
            for h in node.get("headers") or []:
                if not (h.get("key") or "") or str(h["key"]).lower() in (
                        "content-type", "content-length", "host", "accept"):
                    continue
                params.append({"name": str(h["key"]), "in": "header", "required": False,
                               "schema": {"type": "string", "default": str(h.get("value") or "")}})
            op: Dict[str, Any] = {
                "summary": node.get("name") or "Request",
                "operationId": _slug(node.get("name") or "request"),
                "responses": {"200": {"description": "OK"}},
            }
            if node.get("note"):
                op["description"] = node["note"]
            if params:
                op["parameters"] = params
            body = node.get("body") or {}
            if (body.get("raw") or "").strip() and body.get("mode") not in (None, "none"):
                ctype = {"json": "application/json", "xml": "application/xml",
                         "text": "text/plain", "raw": "application/json"}.get(
                             body.get("mode"), "application/json")
                try:
                    example = json.loads(body["raw"]) if ctype.endswith("json") else body["raw"]
                except Exception:  # noqa: BLE001
                    example = body["raw"]
                op["requestBody"] = {"content": {ctype: {"example": example}}}
            method = str(node.get("method") or "GET").lower()
            op["x-ocelot-auth"] = (node.get("auth") or {}).get("type") or "none"
            paths.setdefault(path, {})[method] = op

    walk(_export_nodes(store, nodes))
    return {
        "openapi": "3.1.0",
        "info": {"title": name, "version": "1.0.0",
                 "description": "Exported from Ocelot. Scripts, auth secrets and disabled items are omitted."},
        "servers": [{"url": s} for s in (servers or ["https://example.com"])],
        "paths": paths or {"/": {}},
    }


# ---------------------------------------------------------------- 导出：HAR

def to_har(store, name: str = "Ocelot session",
           nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    import datetime

    entries = []

    def walk(nodes: List[Dict[str, Any]], trail: str = ""):
        for node in nodes:
            if node.get("type") == "folder":
                walk(node.get("children") or [], trail + (node.get("name") or "") + " / ")
                continue
            url = _request_url(node) or "https://example.com"
            base, query = _merge_query(url, node.get("params") or [])
            headers = [{"name": str(h.get("key") or ""), "value": str(h.get("value") or "")}
                       for h in node.get("headers") or [] if h.get("key")]
            post = None
            body = node.get("body") or {}
            if (body.get("raw") or "").strip():
                post = {"mimeType": {"json": "application/json", "xml": "application/xml",
                                     "text": "text/plain"}.get(body.get("mode"), "text/plain"),
                        "text": body.get("raw")}
            entries.append({
                "startedDateTime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "time": 0,
                "comment": trail + (node.get("name") or ""),
                "request": {
                    "method": (node.get("method") or "GET").upper(),
                    "url": base or url,
                    "httpVersion": "HTTP/1.1",
                    "headers": headers,
                    "queryString": [{"name": q["key"], "value": q["value"]} for q in query],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": -1,
                    **({"postData": post} if post else {}),
                },
                "response": {"status": 0, "statusText": "not sent", "httpVersion": "HTTP/1.1",
                             "headers": [], "cookies": [], "content": {"size": 0, "mimeType": ""},
                             "redirectURL": "", "headersSize": -1, "bodySize": -1},
                "cache": {},
                "timings": {"send": 0, "wait": 0, "receive": 0},
                "x-ocelot": {"scripts": node.get("scripts") or {}, "auth": node.get("auth") or {}},
            })

    walk(_export_nodes(store, nodes))
    return {"log": {"version": "1.2", "creator": {"name": "Ocelot", "version": "1.0"},
                    "pages": [{"startedDateTime": entries[0]["startedDateTime"] if entries else "",
                               "id": _slug(name), "title": name, "pageTimings": {}}],
                    "entries": entries}}


# ---------------------------------------------------------------- 极简 YAML 输出

def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or text in ("null", "true", "false", "~") or re.match(r"^[\s:#\-\?{}\[\],&*!|>'\"%@`]", text) \
            or "\n" in text or ": " in text or text.endswith(":"):
        return json.dumps(text, ensure_ascii=False)
    try:
        float(text)
        return json.dumps(text, ensure_ascii=False)
    except ValueError:
        pass
    return text


def to_yaml(data: Any, indent: int = 0) -> str:
    """输出够用的 YAML：字典 / 列表 / 标量，多行字符串走 JSON 转义（YAML 超集）。"""
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return pad + "{}\n"
        out = []
        for key, value in data.items():
            k = _yaml_scalar(key)
            if isinstance(value, (dict, list)) and value:
                out.append(f"{pad}{k}:\n" + to_yaml(value, indent + 1))
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(value) if not isinstance(value, (dict, list)) else ('{}' if isinstance(value, dict) else '[]')}\n")
        return "".join(out)
    if isinstance(data, list):
        if not data:
            return pad + "[]\n"
        out = []
        for item in data:
            if isinstance(item, dict) and item:
                inner = to_yaml(item, indent + 1)
                first, rest = inner.split("\n", 1)
                out.append(f"{pad}- {first.lstrip()}\n{rest}")
            elif isinstance(item, list) and item:
                out.append(f"{pad}-\n" + to_yaml(item, indent + 1))
            else:
                out.append(f"{pad}- {_yaml_scalar(item) if not isinstance(item, (dict, list)) else ''}\n")
        return "".join(out)
    return pad + _yaml_scalar(data) + "\n"


# ---------------------------------------------------------------- 导入

def _mk_request(name: str, method: str, url: str, **fields) -> Dict[str, Any]:
    req = new_request(name or "Untitled Request", (method or "GET").upper(), url or "")
    for key, value in fields.items():
        if value is not None:
            req[key] = value
    return req


# 导出时写死的通用名：导入时不要拿它当集合名（否则每次往返都多一层「Ocelot Collection」）
_GENERIC_NAMES = {
    "ocelot collection", "ocelot api", "imported", "collection", "collections",
    "untitled collection", "postman collection", "api collection", "new collection",
}


def collection_name(*candidates: Any) -> str:
    """从若干候选里挑一个像样的集合名：优先非通用名，其次任意非空，最后空串。"""
    texts = [str(c or "").strip() for c in candidates]
    for text in texts:
        if text and text.lower() not in _GENERIC_NAMES:
            return text[:80]
    for text in texts:
        if text:
            return text[:80]
    return ""


def wrap_collection(items: List[Dict[str, Any]], name: Any, fallback: str = "") -> List[Dict[str, Any]]:
    """把一份集合包成同名文件夹（集合在侧栏里就该是一个目录）。

    - 只有一个请求、且没有任何集合信息 → 保持单条请求，不套壳；
    - 里面已经是一个同名文件夹 → 不重复套。
    """
    nodes = [x for x in items if x]
    if not nodes:
        return []
    title = collection_name(name, fallback)
    if not title:
        return nodes
    if len(nodes) == 1 and nodes[0].get("type") == "folder" and \
            (nodes[0].get("name") or "").strip() == title:
        return nodes
    folder = new_folder(title)
    folder["children"] = nodes
    return [folder]


def _from_postman_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if "item" in item:
        folder = new_folder(str(item.get("name") or "Folder"))
        extra = item.get("x-ocelot") or {}
        if extra.get("folderAuth"):
            folder["auth"] = extra["folderAuth"]
        folder["children"] = [x for x in (_from_postman_item(c) for c in item.get("item") or []) if x]
        return folder
    if "request" not in item:
        return None
    r = item.get("request")
    if isinstance(r, str):
        return _mk_request(str(item.get("name") or "Request"), "GET", r)
    url = r.get("url")
    params: List[Dict[str, Any]] = []
    if isinstance(url, dict):
        for q in url.get("query") or []:
            if not isinstance(q, dict):
                continue
            params.append(kv(str(q.get("key") or ""), str(q.get("value") or ""),
                             not q.get("disabled")))
        raw_url = str(url.get("raw") or "")
        if not raw_url:
            host = url.get("host")
            host = ".".join(host) if isinstance(host, list) else str(host or "")
            path = url.get("path")
            path = "/".join(path) if isinstance(path, list) else str(path or "")
            raw_url = (host + "/" + path.lstrip("/")) if host else path
            if not raw_url.startswith("http") and host:
                raw_url = "https://" + raw_url
    else:
        raw_url = str(url or "")
    base, inline = _merge_query(raw_url, [])
    for row in inline:
        if not any(p["key"] == row["key"] and p["value"] == row["value"] for p in params):
            params.append(row)

    headers = [kv(str(h.get("key") or ""), str(h.get("value") or ""), not h.get("disabled"))
               for h in r.get("header") or [] if isinstance(h, dict) and h.get("key")]
    body = _import_postman_body(r.get("body") or {})
    auth = _import_postman_auth(r.get("auth") or {})
    scripts = {"pre": "", "post": ""}
    for ev in item.get("event") or []:
        listen = ev.get("listen")
        script = ev.get("script") or {}
        code = script.get("exec")
        text = "\n".join(code) if isinstance(code, list) else str(code or "")
        if listen == "prerequest":
            scripts["pre"] = text
        elif listen in ("test", "post-response"):
            scripts["post"] = text
    extra = item.get("x-ocelot") or {}
    if extra.get("auth"):
        auth = extra["auth"]
    cookies = extra.get("cookies") or []
    note = _text_of(r.get("description")) or _text_of(item.get("description"))
    req = _mk_request(str(item.get("name") or "Request"), r.get("method") or "GET",
                      base or raw_url, params=params, headers=headers, body=body,
                      auth=auth, cookies=cookies, scripts=scripts, note=note)
    if (req.get("method") or "").upper() == "WS":
        from .ws_panel import ensure_ws

        req["method"] = "WS"
        req["ws"] = extra.get("ws") if isinstance(extra.get("ws"), dict) else {}
        ensure_ws(req)
    elif (req.get("method") or "").upper() == "SSE":
        from .sse_panel import ensure_sse

        req["method"] = "SSE"
        req["sse"] = extra.get("sse") if isinstance(extra.get("sse"), dict) else {}
        ensure_sse(req)
    return req


def _import_postman_body(body: Dict[str, Any]) -> Dict[str, Any]:
    mode = body.get("mode")
    out = {"mode": "none", "raw": "", "form": [], "file": ""}
    if mode == "raw":
        lang = ((body.get("options") or {}).get("raw") or {}).get("language") or "json"
        mode_name = "json" if lang == "json" else ("xml" if lang == "xml" else "text")
        raw = body.get("raw")
        if not isinstance(raw, str):
            raw = json.dumps(raw, ensure_ascii=False, indent=2) if raw else ""
        out.update(mode=mode_name, raw=raw, raw_lang=lang if lang else "text")
        if lang not in ("json", "xml", "text"):
            out["mode"] = "raw"
        return out
    if mode in ("formdata", "urlencoded"):
        rows = []
        for item in body.get(mode) or []:
            if not isinstance(item, dict):
                continue
            kind = "file" if item.get("type") == "file" else "text"
            value = item.get("src") if kind == "file" else item.get("value")
            if isinstance(value, list):
                value = value[0] if value else ""
            rows.append({"key": str(item.get("key") or ""), "value": str(value or ""),
                         "enabled": not item.get("disabled"), "type": kind})
        out.update(mode="form" if mode == "formdata" else "urlencoded", form=rows)
        return out
    if mode == "file":
        src = (body.get("file") or {}).get("src") or ""
        out.update(mode="binary", file=str(src))
        return out
    if mode == "graphql":
        out.update(mode="json", raw=json.dumps(body.get("graphql") or {}, ensure_ascii=False))
        return out
    return out


def _import_postman_auth(auth: Dict[str, Any]) -> Dict[str, Any]:
    out = {"type": "none", "token": "", "username": "", "password": "",
           "key": "", "value": "", "add_to": "header"}
    kind = auth.get("type")
    if not kind or kind in ("noauth", "none"):
        return out

    def pick(section: str, key: str) -> str:
        for row in auth.get(section) or []:
            if isinstance(row, dict) and row.get("key") == key:
                return str(row.get("value") or "")
        return ""

    if kind == "bearer":
        out.update(type="bearer", token=pick("bearer", "token"))
    elif kind == "basic":
        out.update(type="basic", username=pick("basic", "username"),
                   password=pick("basic", "password"))
    elif kind == "apikey":
        out.update(type="apikey", key=pick("apikey", "key"), value=pick("apikey", "value"),
                   add_to=pick("apikey", "in") or "header")
    elif kind == "jwt":
        out.update(type="jwt", jwt_mode="manual", jwt_token=pick("jwt", "token"))
    elif kind == "oauth2":
        mapping = {
            "client_id": "oauth_client_id", "client_secret": "oauth_client_secret",
            "access_token": "oauth_access_token", "refresh_token": "oauth_refresh_token",
            "token_url": "oauth_token_url", "auth_url": "oauth_auth_url",
            "scope": "oauth_scope", "username": "oauth_username",
            "password": "oauth_password", "issuer": "oauth_issuer",
            "state": "oauth_state", "token_auth_method": "oauth_token_auth_method",
        }
        out["type"] = "oauth2"
        for src, dst in mapping.items():
            out[dst] = pick("oauth2", src)
        if not out.get("oauth_grant"):
            out["oauth_grant"] = ("implicit" if out["oauth_access_token"]
                                  else "client_credentials")
    elif kind == "awsv4":
        out.update(type="awsv4",
                   aws_access_key_id=pick("awsv4", "accessKey"),
                   aws_secret_access_key=pick("awsv4", "secretKey"),
                   aws_session_token=pick("awsv4", "sessionToken"),
                   aws_region=pick("awsv4", "region") or "us-east-1",
                   aws_service=pick("awsv4", "service") or "execute-api")
    elif kind == "digest":
        out.update(type="digest",
                   digest_username=pick("digest", "username"),
                   digest_password=pick("digest", "password"),
                   digest_realm=pick("digest", "realm"),
                   digest_nonce=pick("digest", "nonce"),
                   digest_algorithm=pick("digest", "algorithm") or "MD5",
                   digest_qop=pick("digest", "qop") or "auto",
                   digest_opaque=pick("digest", "opaque"))
    return out


def _from_hoppscotch(data: Any, fallback: str = "") -> List[Dict[str, Any]]:
    def convert_requests(requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for item in requests or []:
            if not isinstance(item, dict):
                continue
            headers = [kv(str(h.get("key") or ""), str(h.get("value") or ""),
                          h.get("active", True) is not False)
                       for h in item.get("headers") or [] if isinstance(h, dict) and h.get("key")]
            params = [kv(str(p.get("key") or ""), str(p.get("value") or ""),
                         p.get("active", True) is not False)
                      for p in item.get("params") or [] if isinstance(p, dict) and p.get("key")]
            body_raw = ""
            body_mode = "none"
            body = item.get("body") or {}
            ctype = str(body.get("contentType") or "")
            content = body.get("body")
            if content:
                body_raw = str(content)
                body_mode = ("json" if "json" in ctype else
                             "xml" if "xml" in ctype else "text")
            auth = _hoppscotch_auth(item.get("auth") or {})
            out.append(_mk_request(str(item.get("name") or "Request"), item.get("method") or "GET",
                                   str(item.get("endpoint") or ""), headers=headers,
                                   params=params, auth=auth,
                                   body={"mode": body_mode, "raw": body_raw, "form": [], "file": ""}))
        return out

    def convert_folders(folders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for folder in folders or []:
            if not isinstance(folder, dict):
                continue
            node = new_folder(str(folder.get("name") or "Folder"))
            node["children"] = (convert_folders(folder.get("folders") or [])
                                + convert_requests(folder.get("requests") or []))
            out.append(node)
        return out

    colls = [c for c in (data if isinstance(data, list) else [data]) if isinstance(c, dict)]
    roots = []
    for i, coll in enumerate(colls):
        children = (convert_folders(coll.get("folders") or [])
                    + convert_requests(coll.get("requests") or []))
        name = collection_name(coll.get("name"),
                               f"{fallback}-{i + 1}" if len(colls) > 1 else fallback)
        roots.extend(wrap_collection(children, name))
    return roots


def _hoppscotch_auth(auth: Dict[str, Any]) -> Dict[str, Any]:
    out = {"type": "none", "token": "", "username": "", "password": "",
           "key": "", "value": "", "add_to": "header"}
    kind = str(auth.get("authType") or "none")
    if kind == "bearer":
        out.update(type="bearer", token=str(auth.get("token") or ""))
    elif kind == "basic":
        out.update(type="basic", username=str(auth.get("username") or ""),
                   password=str(auth.get("password") or ""))
    elif kind in ("api-key", "apikey"):
        out.update(type="apikey", key=str(auth.get("key") or ""),
                   value=str(auth.get("value") or ""),
                   add_to="query" if str(auth.get("addTo") or "") == "query" else "header")
    return out


def _from_insomnia(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    resources = data.get("resources") or []
    groups = {r.get("_id"): r for r in resources if r.get("_type") == "request_group"}
    by_parent: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for res in resources:
        if res.get("_type") not in ("request", "request_group"):
            continue
        by_parent.setdefault(res.get("parentId"), []).append(res)

    def build(parent: Optional[str]) -> List[Dict[str, Any]]:
        out = []
        for res in by_parent.get(parent, []):
            if res.get("_type") == "request_group":
                folder = new_folder(str(res.get("name") or "Folder"))
                folder["children"] = build(res.get("_id"))
                out.append(folder)
                continue
            headers = [kv(str(h.get("name") or ""), str(h.get("value") or ""),
                          not h.get("disabled"))
                       for h in res.get("headers") or [] if h.get("name")]
            params = [kv(str(p.get("name") or ""), str(p.get("value") or ""),
                         not p.get("disabled"))
                      for p in res.get("parameters") or [] if p.get("name")]
            body = res.get("body") or {}
            mime = str(body.get("mimeType") or "")
            raw = str(body.get("text") or "")
            mode = "none"
            if raw:
                mode = ("json" if "json" in mime else
                        "xml" if "xml" in mime else
                        "form" if "form" in mime else "text")
            form = []
            if mode == "form":
                for row in body.get("params") or []:
                    if isinstance(row, dict):
                        form.append({"key": str(row.get("name") or ""),
                                     "value": str(row.get("value") or ""),
                                     "enabled": not row.get("disabled"), "type": "text"})
            out.append(_mk_request(str(res.get("name") or "Request"), res.get("method") or "GET",
                                   str(res.get("url") or ""), headers=headers, params=params,
                                   body={"mode": mode, "raw": raw, "form": form, "file": ""}))
        return out

    roots = build(None)
    if not roots:
        roots = build("__WORKSPACE_ID__")
    if not roots:
        # 有的导出把 workspace 也写成资源、parentId 指向它，或者干脆丢了父节点：
        # 这时把所有「父节点不是已知分组」的资源都当根，避免整份导入为空。
        known = set(groups) | {None}
        loose = [r for r in resources
                 if r.get("_type") in ("request", "request_group")
                 and r.get("parentId") not in known]
        if loose:
            orphan: Dict[Optional[str], List[Dict[str, Any]]] = {}
            for res in loose:
                orphan.setdefault("__root__", []).append(res)
            by_parent.update(orphan)
            roots = build("__root__")
    if not roots:
        return []
    # 集合名优先取 workspace 名，其次文件名
    workspace = next((str(r.get("name") or "") for r in resources
                      if r.get("_type") == "workspace" and r.get("name")), "")
    return wrap_collection(roots, collection_name(workspace, fallback))


def _from_har(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    log = data.get("log") or {}
    page = (log.get("pages") or [{}])[0] or {}
    folder = new_folder(collection_name(page.get("title"), fallback) or "HAR")
    children = []
    for entry in log.get("entries") or []:
        req = entry.get("request") or {}
        headers = [kv(str(h.get("name") or ""), str(h.get("value") or ""))
                   for h in req.get("headers") or [] if h.get("name")]
        params = [kv(str(q.get("name") or ""), str(q.get("value") or ""))
                  for q in req.get("queryString") or [] if q.get("name")]
        post = req.get("postData") or {}
        raw = str(post.get("text") or "")
        mime = str(post.get("mimeType") or "")
        mode = "none"
        if raw:
            mode = "json" if "json" in mime else ("xml" if "xml" in mime else "text")
        name = str((entry.get("comment") or "").split(" / ")[-1]
                   or (req.get("url") or "").rstrip("/").split("/")[-1] or "Request")
        extra = entry.get("x-ocelot") or {}
        children.append(_mk_request(name[:60], req.get("method") or "GET",
                                    str(req.get("url") or ""), headers=headers, params=params,
                                    body={"mode": mode, "raw": raw, "form": [], "file": ""},
                                    scripts=extra.get("scripts") or {"pre": "", "post": ""},
                                    auth=extra.get("auth") or {"type": "none"}))
    folder["children"] = children
    return [folder]


def _from_openapi(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    servers = data.get("servers") or []
    base = ""
    if servers and isinstance(servers[0], dict):
        base = str(servers[0].get("url") or "")
    if not base and data.get("host"):
        schemes = data.get("schemes") or ["https"]
        base = f"{schemes[0]}://{data.get('host')}{data.get('basePath') or ''}"
    root = new_folder(collection_name((data.get("info") or {}).get("title"), fallback)
                      or "OpenAPI")
    items = root["children"]
    for path, methods in (data.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        common = methods.get("parameters") if isinstance(methods.get("parameters"), list) else []
        for method, spec in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch", "head", "options"):
                continue
            spec = spec or {}
            name = str(spec.get("summary") or spec.get("operationId") or f"{method.upper()} {path}")
            url = base.rstrip("/") + path
            headers = []
            params = []
            for p in list(common) + list(spec.get("parameters") or []):
                if not isinstance(p, dict) or not p.get("name"):
                    continue
                ex = (p.get("schema") or {}).get("default", p.get("example", ""))
                if str(p.get("in") or "") == "header":
                    headers.append(kv(str(p["name"]), str(ex)))
                elif str(p.get("in") or "query") == "query":
                    params.append(kv(str(p["name"]), str(ex)))
            body = {"mode": "none", "raw": "", "form": [], "file": ""}
            content = ((spec.get("requestBody") or {}).get("content") or {})
            for ctype, cspec in content.items():
                example = (cspec or {}).get("example")
                if example is None:
                    example = ((cspec or {}).get("schema") or {}).get("example")
                if example is None:
                    continue
                raw = example if isinstance(example, str) else json.dumps(
                    example, ensure_ascii=False, indent=2)
                mode = "json" if "json" in ctype else ("xml" if "xml" in ctype else "text")
                body = {"mode": mode, "raw": raw, "form": [], "file": ""}
                headers.append(kv("Content-Type", ctype))
                break
            items.append(_mk_request(name[:60], method.upper(), url, headers=headers,
                                     params=params, body=body,
                                     note=str(spec.get("description") or "")))
    return [root]


# ---------------------------------------------------------------- 顶层识别

def sanitize(text: str) -> str:
    """去掉 BOM 与首尾空白：Windows 上编辑过的 JSON 常带 U+FEFF，
    不清掉 json.loads 会直接报 "Unexpected UTF-8 BOM"。"""
    if not text:
        return ""
    return text.lstrip("\ufeff").replace("\ufeff", "").strip()


def detect_format(text: str) -> str:
    """按内容猜格式（比看扩展名可靠：很多工具导出的都是 .json）。"""
    text = sanitize(text)
    if not text:
        return "unknown"
    head = text[:6000]
    low = head.lower()
    if low.startswith(("openapi:", "swagger:")):
        return "openapi"
    if low.startswith("curl "):
        return "curl"
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001  可能是 YAML
        if re.match(r"^[\w.-]+:\s", head) and "openapi" in low:
            return "openapi"
        return "unknown"
    return format_of_data(data)


def format_of_data(data: Any) -> str:
    """已经解析成对象的输入，判断它来自哪个工具。"""
    if isinstance(data, list):
        first = next((x for x in data if isinstance(x, dict)), None)
        if first is None:
            return "unknown"
        if "endpoint" in first or "folders" in first or "v" in first:
            return "hoppscotch"
        if "request" in first or "item" in first:
            return "postman"
        if first.get("type") in ("folder", "request") and "name" in first:
            return "native"
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    if data.get("format") == "reqly-collection":
        return "native"
    log = data.get("log")
    if isinstance(log, dict) and "entries" in log:
        return "har"
    if data.get("_type") == "export" or "__export_format" in data:
        return "insomnia"
    if "apiCollection" in data:
        return "apifox"
    if isinstance(data.get("collections"), list):
        return "postman_dump"
    if data.get("v") in (1, 2) and ("requests" in data or "folders" in data):
        return "hoppscotch"
    if "openapi" in data or "swagger" in data:
        return "openapi"
    if "info" in data and "item" in data:
        if "x-ocelot" in data:
            return "ocelot"
        if "apifox" in json.dumps(data.get("info") or {}, ensure_ascii=False).lower():
            return "apifox"
        return "postman"
    if "item" in data:
        return "postman"                     # 少了 info 也算 Postman 集合
    if "request" in data:
        return "postman"                     # 单个请求条目
    if isinstance(data.get("values"), list) and "name" in data:
        return "env_file"                    # Postman / Apifox 的环境变量文件
    if isinstance(data.get("requests"), list):
        return "postman_v1"
    if isinstance(data.get("resources"), list):
        return "insomnia"
    return "unknown"


def _yaml_load(text: str) -> Any:
    """极简 YAML 解析：够读常见的 OpenAPI 文档。

    支持：块状映射 / 列表、缩进嵌套、引号字符串（含 JSON 转义）、行内 [..] 与 {..}、
    ``|`` / ``>`` 块文本、注释、true/false/null/数字。不支持锚点与多文档。
    """
    lines = []
    for raw in text.replace("\t", "  ").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.strip() in ("---", "..."):
            continue
        lines.append(raw.rstrip())

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def scalar(token: str) -> Any:
        token = token.strip()
        if not token:
            return ""
        if token[0] in "[{":
            try:
                return json.loads(token)
            except Exception:  # noqa: BLE001
                inner = token[1:-1].strip()
                if token[0] == "[":
                    return [scalar(x) for x in inner.split(",") if x.strip()]
                out = {}
                for part in inner.split(","):
                    k, _, v = part.partition(":")
                    if k.strip():
                        out[str(scalar(k))] = scalar(v)
                return out
        if token[0] == '"':
            try:
                return json.loads(token)
            except Exception:  # noqa: BLE001
                return token.strip('"')
        if token[0] == "'" and token.endswith("'"):
            return token[1:-1].replace("''", "'")
        low = token.lower()
        if low in ("true", "yes"):
            return True
        if low in ("false", "no"):
            return False
        if low in ("null", "~"):
            return None
        try:
            return int(token)
        except ValueError:
            pass
        try:
            return float(token)
        except ValueError:
            return token

    def parse_block(index: int, indent: int) -> Tuple[Any, int]:
        # 判断是列表还是映射
        if index < len(lines) and lines[index].lstrip().startswith("- "):
            out_list: List[Any] = []
            while index < len(lines):
                line = lines[index]
                if indent_of(line) != indent or not line.lstrip().startswith("- "):
                    break
                rest = line.lstrip()[2:]
                if rest.strip() and ":" in rest and not rest.strip().startswith(("{", "[")):
                    # - key: value 开启一个映射项
                    item: Dict[str, Any] = {}
                    key, _, value = rest.partition(":")
                    index += 1
                    if value.strip():
                        item[str(scalar(key))] = scalar(value)
                    else:
                        child, index = _child(index, indent + 2)
                        item[str(scalar(key))] = child
                    while index < len(lines) and indent_of(lines[index]) > indent:
                        sub = lines[index]
                        k, _, v = sub.lstrip().partition(":")
                        if not _:
                            break
                        index += 1
                        if v.strip():
                            if v.strip() in ("|", ">"):
                                text_block, index = _block_text(index, indent_of(sub))
                                item[str(scalar(k))] = text_block
                            else:
                                item[str(scalar(k))] = scalar(v)
                        else:
                            child, index = _child(index, indent_of(sub) + 2)
                            item[str(scalar(k))] = child
                    out_list.append(item)
                else:
                    if rest.strip():
                        out_list.append(scalar(rest))
                        index += 1
                    else:
                        child, index = _child(index + 1, indent + 2)
                        out_list.append(child)
            return out_list, index

        out_map: Dict[str, Any] = {}
        while index < len(lines):
            line = lines[index]
            if indent_of(line) != indent:
                break
            key, sep, value = line.strip().partition(":")
            if not sep:
                break
            index += 1
            if value.strip() in ("|", ">"):
                text_block, index = _block_text(index, indent)
                out_map[str(scalar(key))] = text_block
            elif value.strip():
                out_map[str(scalar(key))] = scalar(value)
            else:
                child, index = _child(index, indent + 2)
                out_map[str(scalar(key))] = child
        return out_map, index

    def _child(index: int, want: int) -> Tuple[Any, int]:
        if index >= len(lines):
            return None, index
        actual = indent_of(lines[index])
        return parse_block(index, actual if actual >= want else want)

    def _block_text(index: int, parent_indent: int) -> Tuple[str, int]:
        parts = []
        while index < len(lines) and indent_of(lines[index]) > parent_indent:
            parts.append(lines[index].strip())
            index += 1
        return "\n".join(parts) + ("\n" if parts else ""), index

    data, _ = parse_block(0, indent_of(lines[0]) if lines else 0)
    return data


def parse_text(text: str, fallback_name: str = "") -> Tuple[List[Dict[str, Any]], str, str]:
    """把一段文本解析成 (节点列表, 识别到的格式, 错误)。

    fallback_name：文件名 / URL 最后一段。文件里没有集合名时拿它兜底，
    这样导入进来的集合不会叫「Imported」或者空名字。
    """
    text = sanitize(text)
    fmt = detect_format(text)
    if fmt == "unknown":
        return [], fmt, "无法识别的文件格式：既不是 Postman / Apifox / Hoppscotch / Insomnia 集合，也不是 OpenAPI 或 HAR"
    if fmt == "curl":
        return [], fmt, "这是一条 cURL 命令，请用「从剪贴板导入」"
    if fmt == "env_file":
        return [], fmt, "这是环境变量文件，不是集合；请在「设置 → 环境变量」里导入"
    if fmt == "openapi" and not text.startswith("{"):
        try:
            data = _yaml_load(text)
        except Exception as exc:  # noqa: BLE001
            return [], fmt, f"YAML 解析失败：{exc}"
        if not isinstance(data, dict):
            return [], fmt, "YAML 内容不是 OpenAPI 文档"
    else:
        try:
            data = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            return [], fmt, f"JSON 解析失败：{exc}"

    if fmt == "ocelot":
        nodes = _from_ocelot(data, fallback_name)
    elif fmt in ("postman", "apifox"):
        if "apiCollection" in (data or {}):
            nodes = _from_apifox(data, fallback_name)
        else:
            # 集合在侧栏里必须是一个目录：用文件里的集合名建一层，里面的文件夹
            # 保持原来的层级。以前直接把 item 摊在根上，导入完看起来像「没建目录」。
            nodes = _from_postman_any(data, fallback_name)
    elif fmt == "postman_dump":
        nodes = _from_postman_dump(data, fallback_name)
    elif fmt == "postman_v1":
        nodes = _from_postman_v1(data, fallback_name)
    elif fmt == "hoppscotch":
        nodes = _from_hoppscotch(data, fallback_name)
    elif fmt == "insomnia":
        nodes = _from_insomnia(data, fallback_name)
    elif fmt == "har":
        nodes = _from_har(data, fallback_name)
    elif fmt == "openapi":
        nodes = _from_openapi(data, fallback_name)
    elif fmt == "native":
        raw_nodes = data.get("collections") if isinstance(data, dict) else data
        nodes = [_normalize_import(n) for n in (raw_nodes or []) if isinstance(n, dict)]
    else:
        return [], fmt, "无法识别的文件格式"
    if not nodes:
        return [], fmt, _empty_hint(fmt, data)
    return nodes, fmt, ""


def _empty_hint(fmt: str, data: Any) -> str:
    """识别成功但一个请求都没解析出来时，给一句能对症的话。"""
    if fmt in ("apifox",) and isinstance(data, dict) and "apiCollection" in data:
        return "识别为 Apifox 集合，但里面没有可导入的接口"
    if isinstance(data, dict) and isinstance(data.get("values"), list):
        return "这是环境变量文件（Postman Environment），不是集合；集合请从 Collection 导出"
    if isinstance(data, dict) and (data.get("item") == [] or data.get("apiCollection") == []):
        return "集合是空的：文件里没有任何请求"
    return "文件里没有可导入的请求"


def _from_postman_any(data: Any, fallback: str = "") -> List[Dict[str, Any]]:
    """Postman 系（含单个请求、数组、缺 info 的裸集合），集合名当目录名。"""
    if isinstance(data, list):
        out: List[Dict[str, Any]] = []
        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                continue
            items = [x for x in (_from_postman_item(i2) for i2 in entry.get("item") or []) if x]
            info = entry.get("info") or {}
            out.extend(wrap_collection(items, info.get("name") or entry.get("name"),
                                       f"{fallback}-{i + 1}" if len(data) > 1 else fallback))
        return out
    if not isinstance(data, dict):
        return []
    items = data.get("item")
    if isinstance(items, dict):
        items = [items]
    single = not items and "request" in data
    if single:
        items = [data]
    nodes = [x for x in (_from_postman_item(i) for i in items or []) if x]
    if single and not (data.get("info") or {}).get("name"):
        # 单个请求的 JSON：就该是一条请求，别硬套一层目录
        return nodes
    info = data.get("info") or {}
    return wrap_collection(nodes, info.get("name") or data.get("name"), fallback)


def _from_postman_dump(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    """Postman「Export Data」导出的整包 dump：collections + environments。"""
    out: List[Dict[str, Any]] = []
    colls = [c for c in data.get("collections") or [] if isinstance(c, dict)]
    for i, coll in enumerate(colls):
        info = coll.get("info") or {}
        name = collection_name(info.get("name"), coll.get("name"),
                               f"{fallback}-{i + 1}" if len(colls) > 1 else fallback)
        folder = wrap_collection(
            [x for x in (_from_postman_item(i2) for i2 in coll.get("item") or []) if x],
            name, fallback)
        out.extend(folder)
    return out


def _from_postman_v1(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    """Postman v1（很老的格式）：requests + folders + order。"""
    reqs = {r.get("id"): r for r in data.get("requests") or [] if isinstance(r, dict)}
    folders = {f.get("id"): f for f in data.get("folders") or [] if isinstance(f, dict)}

    def one(r: Dict[str, Any]) -> Dict[str, Any]:
        headers: List[Dict[str, Any]] = []
        raw = r.get("headers")
        if isinstance(raw, str):
            for line in raw.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    if key.strip():
                        headers.append(kv(key.strip(), value.strip()))
        elif isinstance(raw, list):
            headers = [kv(str(h.get("key") or h.get("name") or ""), str(h.get("value") or ""),
                          not h.get("disabled")) for h in raw
                       if isinstance(h, dict) and (h.get("key") or h.get("name"))]
        body = {"mode": "none", "raw": "", "form": [], "file": ""}
        mode = str(r.get("dataMode") or "")
        if mode == "params":
            rows = []
            for line in str(r.get("rawModeData") or "").splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    rows.append({"key": key, "value": value, "enabled": True, "type": "text"})
            body = {"mode": "form", "raw": "", "form": rows, "file": ""}
        elif mode == "raw":
            raw_body = str(r.get("rawModeData") or "")
            body = {"mode": "json" if raw_body.strip().startswith(("{", "[")) else "text",
                    "raw": raw_body, "form": [], "file": ""}
        return _mk_request(str(r.get("name") or "Request"), r.get("method") or "GET",
                           str(r.get("url") or ""), headers=headers, body=body,
                           note=str(r.get("description") or ""))

    def walk(order: List[Any]) -> List[Dict[str, Any]]:
        out = []
        for oid in order or []:
            if oid in folders:
                f = folders[oid]
                node = new_folder(str(f.get("name") or "Folder"))
                node["children"] = walk(f.get("order") or [])
                out.append(node)
            elif oid in reqs:
                out.append(one(reqs[oid]))
        return out

    roots = walk(data.get("order") or [])
    if not roots:
        roots = [one(r) for r in reqs.values()]
        for f in folders.values():
            node = new_folder(str(f.get("name") or "Folder"))
            node["children"] = walk(f.get("order") or [])
            if node["children"]:
                roots.append(node)
    return wrap_collection(roots, data.get("name") or data.get("id"), fallback)


def _join_base(base: str, path: str) -> str:
    base = (base or "").strip().rstrip("/")
    path = (path or "").strip()
    if not base:
        return path
    if not path:
        return base
    if path.lower().startswith(("http://", "https://")):
        return path
    return base + "/" + path.lstrip("/")


def _from_apifox(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    """Apifox 自有格式（apiCollection）以及它的 Postman 兼容导出。"""
    if "apiCollection" not in data:
        return _from_postman_any(data, fallback)
    base = ""
    for key in ("baseUrl", "baseURL", "host"):
        if isinstance(data.get(key), str) and data.get(key):
            base = str(data[key])
            break

    def walk(node: Dict[str, Any], folder_base: str) -> Optional[Dict[str, Any]]:
        if not isinstance(node, dict):
            return None
        local_base = str(node.get("baseUrl") or folder_base or "")
        api = node.get("api")
        if isinstance(api, dict):
            return _apifox_request(str(node.get("name") or api.get("name") or "Request"),
                                   api, local_base)
        children = node.get("items") or node.get("children") or node.get("apiList") or []
        if not isinstance(children, list):
            children = []
        folder = new_folder(str(node.get("name") or "Folder"))
        folder["children"] = [x for x in (walk(c, local_base) for c in children) if x]
        return folder

    roots = []
    colls = [c for c in data.get("apiCollection") or [] if isinstance(c, dict)]
    for i, coll in enumerate(colls):
        node = walk(coll, base)
        if node is None:
            continue
        if node.get("type") == "folder" and not (node.get("name") or "").strip():
            node["name"] = collection_name(fallback) or "Apifox"
        if node.get("type") != "folder":
            # 根节点直接是接口（没有目录）：补一层集合目录，别让请求散在根上
            node = wrap_collection([node], collection_name(coll.get("name"), fallback))[0]
        roots.append(node)
    return roots


def _apifox_request(name: str, api: Dict[str, Any], base: str) -> Dict[str, Any]:
    params: List[Dict[str, Any]] = []
    headers: List[Dict[str, Any]] = []
    spec = api.get("parameters") or {}
    if isinstance(spec, dict):
        for row in spec.get("query") or []:
            if isinstance(row, dict) and (row.get("name") or row.get("key")):
                params.append(kv(str(row.get("name") or row.get("key")),
                                 str(row.get("value") if row.get("value") is not None else row.get("example", "")),
                                 row.get("enable", True) is not False))
        for row in spec.get("header") or []:
            if isinstance(row, dict) and (row.get("name") or row.get("key")):
                headers.append(kv(str(row.get("name") or row.get("key")),
                                  str(row.get("value") if row.get("value") is not None else row.get("example", "")),
                                  row.get("enable", True) is not False))
    body = {"mode": "none", "raw": "", "form": [], "file": ""}
    rb = api.get("requestBody") or {}
    if isinstance(rb, dict) and rb:
        ctype = str(rb.get("type") or rb.get("mimeType") or "")
        if "form" in ctype:
            rows = []
            for row in rb.get("parameters") or []:
                if isinstance(row, dict) and (row.get("name") or row.get("key")):
                    rows.append({"key": str(row.get("name") or row.get("key")),
                                 "value": str(row.get("value") or row.get("example") or ""),
                                 "enabled": True, "type": "text"})
            body = {"mode": "form", "raw": "", "form": rows, "file": ""}
        else:
            raw = rb.get("raw") or rb.get("jsonSchema") or rb.get("example") or ""
            if not isinstance(raw, str):
                raw = json.dumps(raw, ensure_ascii=False, indent=2)
            body = {"mode": "json" if "json" in ctype.lower() or raw.strip().startswith(("{", "[")) else "text",
                    "raw": raw, "form": [], "file": ""}
    method = str(api.get("method") or "GET").upper()
    url = _join_base(base, str(api.get("path") or api.get("url") or ""))
    return _mk_request(name, method, url, params=params, headers=headers, body=body,
                       note=str(api.get("description") or ""))


def _from_ocelot(data: Dict[str, Any], fallback: str = "") -> List[Dict[str, Any]]:
    roots = [x for x in (_from_postman_item(i) for i in data.get("item") or []) if x]
    return wrap_collection(roots, (data.get("info") or {}).get("name"), fallback)


def _normalize_import(node: Dict[str, Any]) -> Dict[str, Any]:
    from .importer import _normalize

    return _normalize(node)


def environments_of(text: str) -> List[Dict[str, Any]]:
    """随文件带回来的环境变量：Ocelot 的 x-ocelot、Postman 整包 dump、
    Apifox / Insomnia 的 environments 都认。返回 [{name, vars:[kv...]}]。"""
    try:
        data = json.loads(sanitize(text))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []

    def rows(items: Any, key_name: str = "key") -> List[Dict[str, Any]]:
        out = []
        for row in items or []:
            if not isinstance(row, dict):
                continue
            key = row.get(key_name) or row.get("name") or ""
            if not key:
                continue
            out.append({"key": str(key), "value": str(row.get("value") or ""),
                        "enabled": bool(row.get("enabled", row.get("enable", True))),
                        "type": "text"})
        return out

    found: List[Dict[str, Any]] = []
    extra = data.get("x-ocelot") or {}
    for env in extra.get("environments") or []:
        if isinstance(env, dict) and env.get("vars") is not None:
            found.append({"name": str(env.get("name") or "Imported"),
                          "vars": env.get("vars") or []})
    for env in data.get("environments") or []:
        if not isinstance(env, dict):
            continue
        # Postman dump 用 values，Apifox 用 variables / environments
        items = env.get("values") or env.get("variables") or env.get("vars")
        var_rows = rows(items)
        if var_rows:
            found.append({"name": str(env.get("name") or "Imported"), "vars": var_rows})
    # Insomnia：environment 资源 + environment_variable 子资源
    resources = data.get("resources")
    if isinstance(resources, list):
        envs = {r.get("_id"): r for r in resources
                if isinstance(r, dict) and r.get("_type") == "environment"}
        buckets: Dict[Any, List[Dict[str, Any]]] = {}
        for res in resources:
            if isinstance(res, dict) and res.get("_type") == "environment_variable":
                buckets.setdefault(res.get("parentId"), []).append(
                    {"key": str(res.get("name") or ""), "value": str(res.get("value") or ""),
                     "enabled": not res.get("disabled"), "type": "text"})
        for env_id, var_rows in buckets.items():
            meta = envs.get(env_id) or {}
            if var_rows:
                found.append({"name": str(meta.get("name") or "Imported"), "vars": var_rows})
    # 去重（同名环境只留第一份）
    seen, out = set(), []
    for env in found:
        if env["name"] in seen:
            continue
        seen.add(env["name"])
        out.append(env)
    return out


def _text_of(value: Any) -> str:
    """描述字段可能是字符串，也可能是 {"content": "...", "type": ...}。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("content") or "")
    return ""


def summarize(nodes: List[Dict[str, Any]]) -> Dict[str, int]:
    """统计这次导入带回来了什么 —— 成功页要按项展示，别只给一个总数。"""
    out = {"folders": 0, "requests": 0, "pre": 0, "post": 0,
           "cookies": 0, "auth": 0}

    def walk(items: List[Dict[str, Any]]) -> None:
        for node in items or []:
            if node.get("type") == "folder":
                out["folders"] += 1
                walk(node.get("children") or [])
                continue
            out["requests"] += 1
            scripts = node.get("scripts") or {}
            if (scripts.get("pre") or "").strip():
                out["pre"] += 1
            if (scripts.get("post") or "").strip():
                out["post"] += 1
            if node.get("cookies"):
                out["cookies"] += 1
            if (node.get("auth") or {}).get("type") not in (None, "", "none"):
                out["auth"] += 1

    walk(nodes)
    return out


def count_requests(nodes: List[Dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        if node.get("type") == "folder":
            total += count_requests(node.get("children") or [])
        else:
            total += 1
    return total
