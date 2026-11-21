"""HTTP Digest 认证：RFC 2617 / 7616，标准库实现，零额外依赖。

支持 MD5 / MD5-sess / SHA-256 / SHA-256-sess / SHA-512-256(-sess)、
qop=auth / auth-int、userhash、opaque、401 挑战缓存与 nc 递增。
不保存密码，只缓存 nonce 对应的 cnonce / nc；每次发送重新计算响应摘要。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

_PAIR = re.compile(r'([\w-]+)\s*=\s*(?:"((?:\\.|[^"])*)"|([^,\s]+))')

# (uri, realm, nonce) -> {"cnonce": ..., "nc": int}
_CHALLENGES: Dict[Tuple[str, str, str], Dict[str, Any]] = {}


def _hash_bytes(algorithm: str, text: str) -> bytes:
    alg = (algorithm or "MD5").upper()
    if "SHA-512-256" in alg:
        return hashlib.new("sha512_256", text.encode("utf-8")).digest()
    if "SHA-256" in alg:
        return hashlib.sha256(text.encode("utf-8")).digest()
    return hashlib.md5(text.encode("utf-8")).digest()


def _hex(algorithm: str, text: str) -> str:
    return _hash_bytes(algorithm, text).hex()


def parse_challenge(header: str) -> Dict[str, Any]:
    """从 WWW-Authenticate 里取 Digest 参数（值可能带引号和逗号）。"""
    text = (header or "").strip()
    if not text:
        return {}
    match = re.match(r"^Digest\s+(.*)$", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return {}
    out: Dict[str, Any] = {}
    for key, raw in re.findall(r'([\w-]+)\s*=\s*("(?:\\.|[^"])*"|[^,\s]+)',
                               match.group(1)):
        value = raw[1:-1] if raw.startswith('"') else raw
        out[key.lower()] = re.sub(r'\\(.)', r'\1', value)
    return out


def challenge_from_headers(headers: List[Tuple[str, str]]) -> Dict[str, Any]:
    """多个 WWW-Authenticate 头里挑第一个 Digest 挑战。"""
    for key, value in headers or []:
        if str(key).lower() == "www-authenticate":
            parsed = parse_challenge(str(value))
            if parsed:
                return parsed
    return {}


def _key(uri: str, challenge: Dict[str, Any]) -> Tuple[str, str, str]:
    return (str(uri or ""), str(challenge.get("realm") or ""),
            str(challenge.get("nonce") or ""))


def next_nonce_count(uri: str, challenge: Dict[str, Any]) -> Tuple[str, str]:
    """同一 nonce 复用 cnonce，nc 递增；换 nonce 自动重新计数。"""
    key = _key(uri, challenge)
    state = _CHALLENGES.get(key)
    if not state or not state.get("cnonce"):
        state = {"cnonce": secrets.token_hex(8), "nc": 0}
    state["nc"] = int(state.get("nc") or 0) + 1
    _CHALLENGES[key] = state
    # 只保留最近 64 个挑战，避免长会话里字典无限增长
    if len(_CHALLENGES) > 64:
        oldest = next(iter(_CHALLENGES))
        if oldest != key:
            _CHALLENGES.pop(oldest, None)
    return str(state["cnonce"]), f"{state['nc']:08x}"


def reset(uri: str = "", challenge: Optional[Dict[str, Any]] = None) -> None:
    """stale=TRUE 或用户改了凭据时重置计数。"""
    if uri and challenge:
        _CHALLENGES.pop(_key(uri, challenge), None)
    elif uri:
        for key in list(_CHALLENGES):
            if key[0] == uri:
                _CHALLENGES.pop(key, None)
    else:
        _CHALLENGES.clear()


def build_authorization(username: str, password: str, method: str,
                        uri: str, challenge: Dict[str, Any],
                        body: bytes = b"", qop_pref: str = "auth"
                        ) -> Tuple[str, str]:
    """返回 (Authorization 头值, 错误)。"""
    realm = str(challenge.get("realm") or "")
    nonce = str(challenge.get("nonce") or "")
    if not nonce:
        return "", "Digest 挑战缺少 nonce"
    algorithm = str(challenge.get("algorithm") or "MD5") or "MD5"
    sess = algorithm.lower().endswith("-sess")
    base_alg = algorithm.replace("-sess", "")

    user = str(username or "")
    if str(challenge.get("userhash") or "").lower() == "true":
        user = _hex(base_alg, f"{user}:{realm}")

    ha1 = _hex(base_alg, f"{user}:{realm}:{password or ''}")
    if sess:
        cnonce, nc = next_nonce_count(uri, challenge)
        ha1 = _hex(base_alg, f"{ha1}:{nonce}:{cnonce}")
    else:
        cnonce, nc = next_nonce_count(uri, challenge)

    available = [x.strip() for x in str(challenge.get("qop") or "").split(",") if x.strip()]
    qop = ""
    if qop_pref in available:
        qop = qop_pref
    elif "auth" in available:
        qop = "auth"
    elif available:
        qop = available[0]

    if qop == "auth-int":
        ha2 = _hex(base_alg, f"{method.upper()}:{uri}:{_hex(base_alg, (body or b'').decode('utf-8', 'replace'))}")
    else:
        ha2 = _hex(base_alg, f"{method.upper()}:{uri}")

    if qop:
        response = _hex(base_alg, f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        response = _hex(base_alg, f"{ha1}:{nonce}:{ha2}")

    fields = [
        ("username", user), ("realm", realm), ("nonce", nonce), ("uri", uri),
        ("response", response), ("algorithm", algorithm),
    ]
    if qop:
        fields += [("qop", qop), ("nc", nc), ("cnonce", cnonce)]
    opaque = str(challenge.get("opaque") or "")
    if opaque:
        fields.append(("opaque", opaque))
    if str(challenge.get("userhash") or "").lower() == "true":
        fields.append(("userhash", "true"))
    return "Digest " + ", ".join(f'{k}="{v}"' for k, v in fields), ""
