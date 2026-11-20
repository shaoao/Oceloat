"""`.oce` 集合文件：一个集合一个文件，能读、能改、能进 Git。

为什么用自己的一套格式而不是照抄 Postman 的 JSON：
- **可读**：只写有内容的字段。一条 GET 就是「名字 + 方法 + 地址」三行，
  不是一百多个 `"disabled": false`；
- **可 diff**：key 顺序固定、空值不落盘，改一个地址就只动一行，
  review 和 `git blame` 才有意义；
- **可手改**：拿编辑器改完保存，Ocelot 会发现文件变了并问你用哪一版；
- **不装 UI 状态**：展开/折叠、id、滚动位置这些留在本地存档里，
  写进文件只会制造噪音。

文件长这样::

    {
      "oce": 1,
      "name": "Payments API",
      "tree": {
        "name": "Payments API",
        "children": [
          {"name": "Auth", "children": [
            {"name": "login", "method": "POST", "url": "{{base_url}}/login",
             "body": {"mode": "json", "raw": "{\\n  \\"user\\": \\"{{user}}\\"\\n}"}}
          ]},
          {"name": "list", "url": "{{base_url}}/orders", "params": [{"key": "page", "value": "1"}]}
        ]
      }
    }

约定：**有 children 就是文件夹，没有就是请求**，所以不用写 type；
方法默认 GET，所以 GET 也不用写。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EXT = ".oce"
FORMAT_KEY = "oce"
FORMAT_VERSION = 1
SUFFIX_FILTER = f"Ocelot 集合 (*{EXT})"

# 已经从 node 里单独处理过的键；其余（ws / sio / docs 之类）原样透传，
# 这样以后加新字段不用回来改这里。
_HANDLED = {"id", "type", "name", "open", "children", "method", "url",
            "params", "headers", "cookies", "body", "auth", "scripts", "note"}

_AUTH_EMPTY = {"type": "none", "token": "", "username": "", "password": "",
               "key": "", "value": "", "add_to": "header"}


# ---------------------------------------------------------------- 小工具

def uid() -> str:
    return uuid.uuid4().hex[:10]


def slug(name: str, fallback: str = "collection") -> str:
    """集合名 → 文件名。保留中英文与数字，其余压成 -。"""
    s = re.sub(r'[\\/:*?"<>|\n\r\t]+', "-", (name or "").strip())
    s = re.sub(r"\s+", "-", s).strip(" .-")
    return (s[:64] or fallback)


def suggest_path(name: str, folder: Optional[Path] = None) -> Path:
    base = Path(folder) if folder else (Path.home() / "Documents")
    return base / (slug(name) + EXT)


def is_oce(data: Any) -> bool:
    return isinstance(data, dict) and FORMAT_KEY in data and isinstance(data.get("tree"), dict)


# ---------------------------------------------------------------- 打包
# 内部节点 → 文件里的紧凑写法

def _pack_kv_list(items: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row: Dict[str, Any] = {}
        for key, value in item.items():
            if key == "enabled":
                continue                      # 只在关掉时写，省一行
            if key == "type" and value in ("", "auto", None):
                continue                      # 默认推断，不用写
            if value in ("", None, [], {}):
                continue
            row[key] = value
        if not row.get("key") and not row.get("value"):
            continue                          # 空行不落盘
        if item.get("enabled") is False:
            row["enabled"] = False
        out.append(row)
    return out


def _pack_body(body: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(body, dict):
        return None
    mode = body.get("mode") or "none"
    if mode == "none":
        return None
    out: Dict[str, Any] = {"mode": mode}
    raw = body.get("raw") or ""
    if raw:
        out["raw"] = raw
    form = _pack_kv_list(body.get("form"))
    if form:
        out["form"] = form
    if body.get("raw_lang") and body.get("raw_lang") not in ("json", None) \
            and mode == "raw":
        out["raw_lang"] = body["raw_lang"]
    if body.get("file"):
        out["file"] = body["file"]
    return out


def _pack_auth(auth: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(auth, dict):
        return None
    kind = auth.get("type") or "none"
    if kind == "none":
        return None
    out: Dict[str, Any] = {"type": kind}
    for key, value in auth.items():
        if key == "type" or value in ("", None, [], {}):
            continue
        if key == "add_to" and value == "header":
            continue                          # 默认就是加到请求头
        out[key] = value
    return out


def pack_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """一个节点（请求或文件夹）→ 文件里的写法。"""
    if not isinstance(node, dict):
        return {}
    name = str(node.get("name") or "Untitled")
    kids = node.get("children")
    if isinstance(kids, list):
        out: Dict[str, Any] = {"name": name}
        auth = _pack_auth(node.get("auth"))
        if auth:
            out["auth"] = auth
        if node.get("note"):
            out["note"] = node["note"]
        out["children"] = [k for k in (pack_node(c) for c in kids) if k]
        return out

    out = {"name": name}
    method = str(node.get("method") or "GET").upper()
    if method != "GET":
        out["method"] = method
    if node.get("url"):
        out["url"] = node["url"]
    for key in ("params", "headers", "cookies"):
        rows = _pack_kv_list(node.get(key))
        if rows:
            out[key] = rows
    body = _pack_body(node.get("body"))
    if body:
        out["body"] = body
    auth = _pack_auth(node.get("auth"))
    if auth:
        out["auth"] = auth
    scripts = node.get("scripts") or {}
    if isinstance(scripts, dict):
        kept = {k: v for k, v in scripts.items() if v}
        if kept:
            out["scripts"] = kept
    if node.get("note"):
        out["note"] = node["note"]
    for key, value in node.items():         # ws / sio / 以后的扩展
        if key in _HANDLED or key in out:
            continue
        if value in ("", None, [], {}):
            continue
        out[key] = value
    return out


# ---------------------------------------------------------------- 解包
# 文件里的写法 → 内部节点（补全所有字段，界面不用到处判空）

def _unpack_kv_list(items: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if isinstance(items, dict):             # 容忍 {k: v} 这种手写写法
        items = [{"key": k, "value": v} for k, v in items.items()]
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row.setdefault("key", "")
        row.setdefault("value", "")
        row["enabled"] = bool(row.get("enabled", True))
        row.setdefault("type", "auto")
        out.append(row)
    return out


def _unpack_body(body: Any) -> Dict[str, Any]:
    data = body if isinstance(body, dict) else {}
    return {
        "mode": data.get("mode") or "none",
        "raw": data.get("raw") or "",
        "raw_lang": data.get("raw_lang") or "json",
        "form": _unpack_kv_list(data.get("form")),
        "file": data.get("file") or "",
    }


def _unpack_auth(auth: Any) -> Dict[str, Any]:
    out = dict(_AUTH_EMPTY)
    if isinstance(auth, dict):
        for key, value in auth.items():
            if value is not None:
                out[key] = value
    if out.get("type") in (None, ""):
        out["type"] = "none"
    return out


def unpack_node(data: Dict[str, Any], counter: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """文件里的节点 → 内部节点。id 这里先给新的，加载后由 reconcile_ids 接回旧的。"""
    if not isinstance(data, dict):
        data = {}
    name = str(data.get("name") or "Untitled")
    kids = data.get("children")
    if isinstance(kids, list):
        node: Dict[str, Any] = {
            "id": uid(), "type": "folder", "name": name, "open": True,
            "children": [unpack_node(c, counter) for c in kids if isinstance(c, dict)],
        }
        auth = _pack_auth(data.get("auth"))
        if auth:
            node["auth"] = _unpack_auth(data.get("auth"))
        if data.get("note"):
            node["note"] = str(data["note"])
        return node

    node = {
        "id": uid(),
        "type": "request",
        "name": name,
        "method": str(data.get("method") or "GET").upper(),
        "url": str(data.get("url") or ""),
        "params": _unpack_kv_list(data.get("params")),
        "headers": _unpack_kv_list(data.get("headers")),
        "cookies": _unpack_kv_list(data.get("cookies")),
        "body": _unpack_body(data.get("body")),
        "auth": _unpack_auth(data.get("auth")),
        "scripts": {"pre": "", "post": ""},
        "note": str(data.get("note") or ""),
    }
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        for key, value in scripts.items():
            node["scripts"][key] = str(value or "")
    for key, value in data.items():         # ws / sio 等原样带回来
        if key in _HANDLED or key in node:
            continue
        node[key] = value
    return node


# ---------------------------------------------------------------- 整体

def dump(collection: Dict[str, Any]) -> str:
    """集合 → .oce 文本。key 顺序固定、缩进 2，方便 diff。"""
    name = str(collection.get("name") or "Collection")
    payload = {FORMAT_KEY: FORMAT_VERSION, "name": name, "tree": pack_node(collection)}
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def parse(text: str, fallback_name: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    """文本 → (集合节点, 错误)。"""
    try:
        data = json.loads(text)
    except Exception as exc:                # noqa: BLE001
        return None, f"不是合法的 JSON：{exc}"
    if not is_oce(data):
        return None, "不是 .oce 集合文件"
    version = data.get(FORMAT_KEY)
    if isinstance(version, int) and version > FORMAT_VERSION:
        return None, f"这个文件是更新版本的 Ocelot 写的（格式 v{version}），先升级再打开"
    tree = data["tree"]
    node = unpack_node(tree)
    if node.get("type") != "folder":
        # 单个请求也能存成一个集合：套一层同名文件夹，侧栏里位置才正常
        node = {"id": uid(), "type": "folder", "name": node.get("name") or fallback_name,
                "open": True, "children": [node]}
    node.setdefault("id", uid())
    if not node.get("name"):
        node["name"] = fallback_name or "Collection"
    for key, value in data.items():         # 集合级扩展字段（以后放变量 / 文档）
        if key in (FORMAT_KEY, "name", "tree") or value in ("", None):
            continue
        node[key] = value
    return node, ""


def read_file(path: Path | str) -> Tuple[Optional[Dict[str, Any]], str]:
    path = Path(path)
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        return None, "文件不存在"
    except OSError as exc:
        return None, f"读不了这个文件：{exc}"
    return parse(text, fallback_name=path.stem)


def write_file(path: Path | str, collection: Dict[str, Any]) -> Tuple[bool, str]:
    """原子写入：先写 .tmp 再 replace，中途断电也不会留下半个文件。"""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(dump(collection), "utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        return False, f"写入失败：{exc}"
    return True, ""


def content_hash(collection: Dict[str, Any]) -> str:
    """按「文件里会写什么」算指纹：只看内容，不看 id / 展开状态 / 时间。"""
    text = dump(collection)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def file_hash(path: Path | str) -> str:
    try:
        text = Path(path).read_text("utf-8")
    except OSError:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def reconcile_ids(new: Dict[str, Any], old: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """从磁盘重新读回来时，尽量复用旧的 id。

    打开着的标签、Mock 路由、当前选中项都靠 id 找人；如果每次读文件都换
    一套 id，界面上看起来就像「刚打开的东西全没了」。这里按
    「同层级 + 同类型 + 同名」对一遍，对上的沿用旧 id。
    """
    if not isinstance(old, dict) or not old:
        return new
    old_kids = [k for k in (old.get("children") or []) if isinstance(k, dict)]
    used = set()
    new_kids = new.get("children") or []

    def same_kind(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        return (a.get("type") == "folder") == (b.get("type") == "folder")

    def take(kid: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # 先按名字找；找不到再按位置找 —— 文件里改了个名字，标签不该因此断掉
        for cand in old_kids:
            if id(cand) not in used and same_kind(cand, kid) \
                    and cand.get("name") == kid.get("name"):
                return cand
        index = new_kids.index(kid)
        if index < len(old_kids):
            cand = old_kids[index]
            if id(cand) not in used and same_kind(cand, kid):
                return cand
        return None

    for kid in new_kids:
        match = take(kid)
        if match is None:
            continue
        used.add(id(match))
        kid["id"] = match.get("id") or kid.get("id")
        if kid.get("type") == "folder":
            reconcile_ids(kid, match)
        elif match.get("url") == kid.get("url"):
            kid["url"] = match.get("url")
    if new.get("type") == "folder":
        new["open"] = old.get("open", True)
    return new


def ago(ts: float) -> str:                   # 小工具：给界面显示「刚才 / 5 分钟前」
    delta = max(0.0, time.time() - float(ts or 0))
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    return time.strftime("%m-%d %H:%M", time.localtime(ts))
