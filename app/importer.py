"""导入能力：解析 cURL 命令；集合的导入 / 导出。

cURL 解析已统一到 app/curl_import.py（支持 -F 文件、--data-urlencode、
--flag=value、合并短 flag、URL 查询参数拆分等）；这里只保留兼容旧调用方的
(request, error) 元组签名，集合导入 / 导出逻辑不变。
"""
from __future__ import annotations

from . import i18n

import json
from typing import Any, Dict, List, Optional, Tuple

from .curl_import import CurlParseError, parse_curl as _parse_curl, strip_hints
from .store import kv, new_request, uid


def parse_curl(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """把 cURL 命令解析为请求字典。返回 (request, error)。"""
    try:
        return strip_hints(_parse_curl(text)), ""
    except CurlParseError as exc:
        return None, str(exc)


# ---------------------------------------------------------------- 集合导入导出

def export_collection(store, path: str) -> int:
    data = {
        "format": "reqly-collection",
        "version": 1,
        "collections": store.collections,
        "environments": store.environments,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return len(store.collections)


def _normalize(node: Dict[str, Any]) -> Dict[str, Any]:
    """补全新 id，避免导入后与现有节点冲突。"""
    node = dict(node)
    node["id"] = uid()
    if node.get("type") == "folder":
        node["children"] = [_normalize(c) for c in node.get("children", [])]
    else:
        node.setdefault("type", "request")
        node.setdefault("method", "GET")
        node.setdefault("url", "")
        node.setdefault("params", [])
        node.setdefault("headers", [])
        node.setdefault("body", {"mode": "none", "raw": "", "form": [], "file": ""})
        node.setdefault("auth", {"type": "none", "token": "", "username": "", "password": "",
                                 "key": "", "value": "", "add_to": "header"})
    return node


def import_collection(store, path: str) -> Tuple[int, str]:
    """导入 Reqly 集合或 Postman v2.1 集合。返回 (导入节点数, 错误)。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return 0, i18n.trf("读取失败：{err}", err=exc)

    if isinstance(data, dict) and data.get("format") == "reqly-collection":
        nodes = data.get("collections") or []
    elif isinstance(data, dict) and "info" in data and "item" in data:
        nodes = [_from_postman(data)]
    elif isinstance(data, list):
        nodes = data
    else:
        return 0, "无法识别的集合文件格式"

    count = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        store.collections.append(_normalize(node))
        count += 1
    store.save()
    return count, ""


def _from_postman(collection: Dict[str, Any]) -> Dict[str, Any]:
    def convert(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for item in items:
            if "item" in item:
                out.append({"id": uid(), "type": "folder", "name": item.get("name", "Folder"),
                            "open": True, "children": convert(item.get("item") or [])})
            elif "request" in item:
                r = item["request"]
                if isinstance(r, str):
                    req = new_request(item.get("name", "Request"), "GET", r)
                    out.append(req)
                    continue
                url = r.get("url") or ""
                if isinstance(url, dict):
                    url = url.get("raw", "")
                req = new_request(item.get("name", "Request"),
                                  (r.get("method") or "GET").upper(), url)
                headers = []
                for h in r.get("header") or []:
                    if isinstance(h, dict) and h.get("key"):
                        headers.append(kv(h.get("key"), h.get("value", ""), not h.get("disabled")))
                req["headers"] = headers
                body = r.get("body") or {}
                mode = body.get("mode")
                if mode == "raw":
                    req["body"] = {"mode": "json" if "json" in (body.get("options") or {}).get("raw", {}).get("language", "json") else "text",
                                   "raw": body.get("raw", ""), "form": [], "file": ""}
                elif mode == "urlencoded":
                    req["body"] = {"mode": "urlencoded", "raw": "", "form": [
                        kv(x.get("key", ""), x.get("value", ""), not x.get("disabled"))
                        for x in body.get("urlencoded") or []], "file": ""}
                out.append(req)
        return out

    return {"id": uid(), "type": "folder", "name": collection.get("info", {}).get("name", "Imported"),
            "open": True, "children": convert(collection.get("item") or [])}
