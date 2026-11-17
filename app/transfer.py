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
    if req.get("cookies"):
        extra["cookies"] = req["cookies"]
    if req.get("note"):
        item["request"]["description"] = req["note"]
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


def to_postman(store, name: str = "Ocelot Collection", extra: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "info": {"name": name, "_postman_id": uid(), "schema": POSTMAN_SCHEMA},
        "item": [_postman_node(n) for n in store.collections],
    }
    if extra:
        data["x-ocelot"] = {
            "version": 1,
            "generator": "Ocelot",
            "environments": store.environments,
            "active_env": store.data.get("active_env"),
        }
    return data


def to_ocelot(store, name: str = "Ocelot Collection") -> Dict[str, Any]:
    """Ocelot JSON = Postman v2.1 + x-ocelot 元数据。

    刻意不用私有结构：Postman / Apifox / Insomnia 都能直接导入这份文件，
    我们自己导回来也不丢脚本、认证、Cookie。
    """
    return to_postman(store, name, extra=True)


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


def to_openapi(store, name: str = "Ocelot API") -> Dict[str, Any]:
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

    walk(store.collections)
    return {
        "openapi": "3.1.0",
        "info": {"title": name, "version": "1.0.0",
                 "description": "Exported from Ocelot. Scripts, auth secrets and disabled items are omitted."},
        "servers": [{"url": s} for s in (servers or ["https://example.com"])],
        "paths": paths or {"/": {}},
    }


# ---------------------------------------------------------------- 导出：HAR

def to_har(store, name: str = "Ocelot session") -> Dict[str, Any]:
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

    walk(store.collections)
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
    note = r.get("description") or item.get("description") or ""
    return _mk_request(str(item.get("name") or "Request"), r.get("method") or "GET",
                       base or raw_url, params=params, headers=headers, body=body,
                       auth=auth, cookies=cookies, scripts=scripts,
                       note=str(note) if isinstance(note, str) else "")


def _import_postman_body(body: Dict[str, Any]) -> Dict[str, Any]:
    mode = body.get("mode")
    out = {"mode": "none", "raw": "", "form": [], "file": ""}
    if mode == "raw":
        lang = ((body.get("options") or {}).get("raw") or {}).get("language") or "json"
        mode_name = "json" if lang == "json" else ("xml" if lang == "xml" else "text")
        out.update(mode=mode_name, raw=body.get("raw") or "", raw_lang=lang if lang else "text")
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
    return out


def _from_hoppscotch(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

    roots = []
    for coll in data if isinstance(data, list) else [data]:
        if not isinstance(coll, dict):
            continue
        node = new_folder(str(coll.get("name") or "Imported"))
        node["children"] = (convert_folders(coll.get("folders") or [])
                            + convert_requests(coll.get("requests") or []))
        roots.append(node)
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


def _from_insomnia(data: Dict[str, Any]) -> List[Dict[str, Any]]:
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
    return roots


def _from_har(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    log = data.get("log") or {}
    folder = new_folder("HAR · " + str(((log.get("pages") or [{}])[0] or {}).get("title") or "Import"))
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


def _from_openapi(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    servers = data.get("servers") or []
    base = ""
    if servers and isinstance(servers[0], dict):
        base = str(servers[0].get("url") or "")
    if not base and data.get("host"):
        schemes = data.get("schemes") or ["https"]
        base = f"{schemes[0]}://{data.get('host')}{data.get('basePath') or ''}"
    root = new_folder(str((data.get("info") or {}).get("title") or "OpenAPI Import"))
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

def detect_format(text: str) -> str:
    """按内容猜格式（比看扩展名可靠：很多工具导出的都是 .json）。"""
    stripped = text.lstrip()
    if stripped.startswith("openapi:") or stripped.startswith("swagger:"):
        return "openapi"
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return "unknown"
    if isinstance(data, dict):
        if data.get("format") == "reqly-collection":
            return "native"
        if "log" in data and isinstance(data["log"], dict) and "entries" in (data["log"] or {}):
            return "har"
        if "__export_format" in data or data.get("_type") == "export":
            return "insomnia"
        if "openapi" in data or "swagger" in data:
            return "openapi"
        if "info" in data and "item" in data:
            if "x-ocelot" in data:
                return "ocelot"
            schema = str((data.get("info") or {}).get("schema") or "")
            if "apifox" in json.dumps(data.get("info") or {}, ensure_ascii=False).lower():
                return "apifox"
            return "postman" if "schema" in schema or "getpostman" in schema else "postman"
        if "apiCollection" in data:
            return "apifox"
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            if "endpoint" in data[0] or "folders" in data[0]:
                return "hoppscotch"
            if data[0].get("type") in ("folder", "request") and "name" in data[0]:
                return "native"
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


def parse_text(text: str) -> Tuple[List[Dict[str, Any]], str, str]:
    """把一段文本解析成 (节点列表, 识别到的格式, 错误)。"""
    fmt = detect_format(text)
    if fmt == "unknown" and text.lstrip().startswith(("openapi:", "swagger:")):
        fmt = "openapi"
    if fmt == "unknown":
        return [], fmt, "无法识别的文件格式"
    if fmt == "openapi" and not text.lstrip().startswith("{"):
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
        nodes = _from_ocelot(data)
    elif fmt in ("postman", "apifox"):
        # item 本身就是树，不用再套一层文件夹；否则每次来回导都多一层「Imported」。
        nodes = [x for x in (_from_postman_item(i) for i in data.get("item") or []) if x]
    elif fmt == "hoppscotch":
        nodes = _from_hoppscotch(data)
    elif fmt == "insomnia":
        nodes = _from_insomnia(data)
    elif fmt == "har":
        nodes = _from_har(data)
    elif fmt == "openapi":
        nodes = _from_openapi(data)
    elif fmt == "native":
        raw_nodes = data.get("collections") if isinstance(data, dict) else data
        nodes = [_normalize_import(n) for n in (raw_nodes or []) if isinstance(n, dict)]
    else:
        return [], fmt, "无法识别的文件格式"
    return nodes, fmt, ""


def _from_ocelot(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    roots = [x for x in (_from_postman_item(i) for i in data.get("item") or []) if x]
    return roots


def _normalize_import(node: Dict[str, Any]) -> Dict[str, Any]:
    from .importer import _normalize

    return _normalize(node)


def environments_of(text: str) -> List[Dict[str, Any]]:
    """Ocelot JSON 里带的整套环境变量；别的格式返回空列表。"""
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    extra = (data.get("x-ocelot") or {}) if isinstance(data, dict) else {}
    envs = extra.get("environments") or []
    return [e for e in envs if isinstance(e, dict) and e.get("vars") is not None]


def count_requests(nodes: List[Dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        if node.get("type") == "folder":
            total += count_requests(node.get("children") or [])
        else:
            total += 1
    return total
