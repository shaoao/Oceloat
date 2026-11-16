"""cURL 命令解析：把浏览器 DevTools / 文档里复制的 curl 命令还原成请求对象。

覆盖常用 flag：-X -H -d/--data-raw/--data-binary --data-urlencode -F -u -A -e -b
--url -G -L -k --compressed，以及 `--flag=value` 写法、合并短 flag（-sSL）和
反斜杠续行。解析结果直接匹配 Store.new_request 的 schema，可交给编辑器加载。
"""
from __future__ import annotations

import json
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlsplit

from .store import uid


class CurlParseError(ValueError):
    """命令无法解析时抛出，消息直接展示给用户。"""


def _tokenize(cmd: str) -> List[str]:
    # curl 命令里的续行是「反斜杠 + 换行」，shlex 不认，先折成空格
    text = re.sub(r"\\\s*\r?\n", " ", (cmd or "").strip())
    text = text.replace("\r", " ").replace("\n", " ")
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        # 引号不配对（复制截断常见）时退化为按空白硬拆，尽量救回 URL 和方法
        return text.split()


def _kv_row(key: str, value: str, enabled: bool = True) -> Dict[str, Any]:
    return {"key": key, "value": value, "enabled": enabled, "type": "auto", "desc": ""}


def _looks_like_json(text: str) -> bool:
    s = (text or "").lstrip()
    if not s or s[:1] not in "[{":
        return False
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def parse_curl(cmd: str) -> Dict[str, Any]:
    """把 curl 命令解析成请求 dict；失败抛 CurlParseError。"""
    tokens = _tokenize(cmd)
    if not tokens:
        raise CurlParseError("命令为空，请粘贴完整的 curl 命令")

    # 跳过开头的 curl / env 赋值前缀
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.lower() == "curl" or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", t):
            i += 1
            continue
        break
    if i >= len(tokens) or tokens[0].lower() not in ("curl", "env") \
            and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", tokens[0]):
        raise CurlParseError("这不是 curl 命令，请粘贴以 curl 开头的命令")

    method = ""
    url = ""
    headers: List[Tuple[str, str]] = []
    data_parts: List[str] = []
    urlencoded: List[Tuple[str, str]] = []
    forms: List[Tuple[str, str, bool]] = []      # (key, value, is_file)
    user = ""
    get_mode = False
    follow: Optional[bool] = None
    verify: Optional[bool] = None

    def value_of(tok: str, idx: int, name: str) -> Tuple[str, int]:
        """取 flag 的值：支持 --flag=value 与 --flag value 两种写法。"""
        if tok.startswith("--") and "=" in tok:
            return tok.split("=", 1)[1], idx
        if idx + 1 >= len(tokens):
            raise CurlParseError(f"{name} 后面缺少参数")
        return tokens[idx + 1], idx + 1

    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower()
        if low in ("-x", "--request"):
            method, i = value_of(tok, i, "-X")
            method = method.strip().upper()
        elif low in ("-h", "--header"):
            v, i = value_of(tok, i, "-H")
            k, _, val = v.partition(":")
            if k.strip():
                headers.append((k.strip(), val.strip()))
        elif low in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii"):
            v, i = value_of(tok, i, "-d")
            data_parts.append(v)
        elif low == "--data-urlencode":
            v, i = value_of(tok, i, "--data-urlencode")
            if "=" in v:
                k, _, val = v.partition("=")
                urlencoded.append((k.strip(), val.strip()))
            else:
                urlencoded.append(("", v))
        elif low in ("-f", "--form"):
            v, i = value_of(tok, i, "-F")
            k, _, val = v.partition("=")
            is_file = val.startswith("@")
            forms.append((k.strip(), val[1:].strip() if is_file else val.strip(), is_file))
        elif low in ("-u", "--user"):
            user, i = value_of(tok, i, "-u")
        elif low in ("-a", "--user-agent"):
            v, i = value_of(tok, i, "-A")
            headers.append(("User-Agent", v))
        elif low in ("-e", "--referer"):
            v, i = value_of(tok, i, "-e")
            headers.append(("Referer", v))
        elif low in ("-b", "--cookie"):
            v, i = value_of(tok, i, "-b")
            headers.append(("Cookie", v))
        elif low in ("-l", "--location"):
            follow = True
        elif low in ("-k", "--insecure"):
            verify = False
        elif low in ("-g", "-G", "--get"):
            get_mode = True
        elif low == "--compressed":
            pass
        elif low == "--url":
            url, i = value_of(tok, i, "--url")
        elif tok.startswith("--"):
            # 其它长 flag：带值的吃掉，纯布尔跳过
            if "=" not in tok and i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                i += 1
        elif tok.startswith("-") and len(tok) > 1 and not tok[1].isdigit():
            # 合并短 flag：-sSL 之类；若含取值 flag，剩余部分即值
            body = tok[1:]
            took_value = False
            for pos, ch in enumerate(body):
                if ch.lower() in "xhdfaeb":
                    rest = body[pos + 1:]
                    if rest:
                        value = rest
                    elif i + 1 < len(tokens):
                        value = tokens[i + 1]
                        i += 1
                    else:
                        raise CurlParseError(f"-{ch} 后面缺少参数")
                    took_value = True
                    c = ch.lower()
                    if c == "x":
                        method = value.strip().upper()
                    elif c == "h":
                        k, _, val = value.partition(":")
                        if k.strip():
                            headers.append((k.strip(), val.strip()))
                    elif c == "d":
                        data_parts.append(value)
                    elif c == "f":
                        k, _, val = value.partition("=")
                        is_file = val.startswith("@")
                        forms.append((k.strip(), val[1:].strip() if is_file else val.strip(), is_file))
                    elif c == "u":
                        user = value
                    elif c == "a":
                        headers.append(("User-Agent", value))
                    elif c == "e":
                        headers.append(("Referer", value))
                    elif c == "b":
                        headers.append(("Cookie", value))
                    break
                # 其余字符（s/S/L/v/i…）按布尔处理，继续看下一个
            if not took_value:
                pass
        else:
            if not url:
                url = tok
        i += 1

    if not url:
        raise CurlParseError("命令里没有 URL")
    if "://" not in url:
        url = "http://" + url

    # URL 里已有的查询参数拆成参数行
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else url.split("?", 1)[0]
    params = [_kv_row(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]

    body: Dict[str, Any] = {"mode": "none", "raw": "", "form": [], "file": ""}
    if forms:
        body["mode"] = "form"
        body["form"] = [
            {"key": k, "value": v, "enabled": True,
             "type": "file" if is_file else "auto", "desc": ""}
            for k, v, is_file in forms
        ]
        if not method:
            method = "POST"
    elif urlencoded:
        if get_mode:
            # -G 配合 --data-urlencode：全部拼进查询串
            for k, v in urlencoded:
                params.append(_kv_row(k, v))
        else:
            body["mode"] = "urlencoded"
            body["form"] = [_kv_row(k, v) for k, v in urlencoded]
            if not method:
                method = "POST"
    elif data_parts:
        raw = "&".join(data_parts)
        if get_mode:
            # -G：把数据拼进查询串
            for k, v in parse_qsl(raw, keep_blank_values=True):
                params.append(_kv_row(k, v))
        else:
            body["raw"] = raw
            body["mode"] = "json" if _looks_like_json(raw) else "text"
            if not method:
                method = "POST"

    if not method:
        method = "GET"

    auth: Dict[str, Any] = {"type": "none", "token": "", "username": "", "password": "",
                            "key": "", "value": "", "add_to": "header"}
    if user:
        u, _, p = user.partition(":")
        auth.update({"type": "basic", "username": u, "password": p})

    # Content-Type 交给 body 模式决定，去掉 curl 里重复声明的那个
    lowered = {k.lower() for k, _ in headers}
    if body["mode"] == "json" and "content-type" not in lowered:
        headers.append(("Content-Type", "application/json"))
    elif body["mode"] == "text" and "content-type" not in lowered:
        headers.append(("Content-Type", "text/plain"))

    req = {
        "id": uid(),
        "type": "request",
        "name": f"Imported · {method} {parts.netloc or ''}".strip(" ·"),
        "method": method,
        "url": base,
        "params": params,
        "headers": [_kv_row(k, v) for k, v in headers],
        "body": body,
        "auth": auth,
        "note": "从 cURL 命令导入",
    }
    req["_hints"] = {
        "follow_redirects": follow,
        "verify_ssl": verify,
    }
    return req


def strip_hints(req: Dict[str, Any]) -> Dict[str, Any]:
    """去掉解析附带的设置提示，得到纯净的请求对象（存集合/发请求用）。"""
    clean = dict(req)
    clean.pop("_hints", None)
    return clean
