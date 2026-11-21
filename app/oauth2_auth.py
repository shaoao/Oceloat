"""OAuth 2.0 认证：标准库实现，零额外依赖。

支持四种 grant：
- client_credentials：客户端凭证换 token
- password：用户名 / 密码换 token
- authorization_code：授权码 + PKCE 换 token
- implicit / 手动：直接使用用户粘贴的 token（授权在浏览器完成）

token 缓存在 Store.data["oauth_tokens"]，以 token_url + client_id + scope + grant 为键；
过期前 60 秒自动刷新。刷新失败返回错误，由调用方显示在控制台，绝不静默发送无认证请求。
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

GRANTS = ["client_credentials", "password", "authorization_code", "implicit"]
GRANT_LABELS = {
    "client_credentials": "客户端凭证",
    "password": "密码",
    "authorization_code": "授权码（PKCE）",
    "implicit": "手动 Token",
}

# 缓存条目字段：access_token / refresh_token / expires_at / token_type
CACHE_KEY = "oauth_tokens"


def _cache_key(auth: Dict[str, Any], env: Dict[str, str]) -> str:
    def resolve(v: str) -> str:
        text = str(v or "")
        for name, value in (env or {}).items():
            text = text.replace("{{" + name + "}}", str(value))
        return text

    raw = "|".join(resolve(auth.get(k, "")) for k in
                   ("oauth_token_url", "oauth_client_id", "oauth_scope", "oauth_grant"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{digest}:{auth.get('oauth_grant') or 'client_credentials'}"


def _store_cache(store) -> Dict[str, Any]:
    if store is None:
        return {}
    data = getattr(store, "data", None)
    if not isinstance(data, dict):
        return {}
    cache = data.get(CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        data[CACHE_KEY] = cache
    return cache


def cached_token(auth: Dict[str, Any], store, env: Dict[str, str]) -> Optional[Dict[str, Any]]:
    entry = _store_cache(store).get(_cache_key(auth, env))
    if not isinstance(entry, dict) or not entry.get("access_token"):
        return None
    expires = float(entry.get("expires_at") or 0)
    # expires_at=0 表示服务端没给过期时间：用 1 小时兜底，避免每次都重新换 token
    if expires and time.time() > expires - 60:
        return None
    if not expires and time.time() > float(entry.get("cached_at") or 0) + 3500:
        return None
    return entry


def save_token(auth: Dict[str, Any], store, env: Dict[str, str],
               data: Dict[str, Any]) -> None:
    if store is None:
        return
    entry = dict(data)
    entry.setdefault("cached_at", time.time())
    if entry.get("expires_in"):
        try:
            entry["expires_at"] = time.time() + float(entry["expires_in"])
        except (TypeError, ValueError):
            entry["expires_at"] = 0
    _store_cache(store)[_cache_key(auth, env)] = entry
    try:
        store.save()
    except Exception:       # noqa: BLE001 - 缓存写失败不影响本次请求
        pass


def clear_token(auth: Dict[str, Any], store, env: Dict[str, str]) -> None:
    _store_cache(store).pop(_cache_key(auth, env), None)


def pkce(verifier: str = "") -> Tuple[str, str]:
    """返回 (verifier, challenge)。verifier 为空时生成一个新的。"""
    import re as _re

    if not verifier or not _re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(auth: Dict[str, Any], env: Dict[str, str]) -> str:
    """拼授权地址（授权码 + PKCE）。浏览器打开后把 code 粘回界面即可。"""
    auth_url = str(auth.get("oauth_auth_url") or "")
    if not auth_url:
        return ""
    verifier, challenge = pkce(str(auth.get("oauth_code_verifier") or ""))
    params = {
        "response_type": "code",
        "client_id": str(auth.get("oauth_client_id") or ""),
        "redirect_uri": str(auth.get("oauth_redirect_uri") or ""),
        "scope": str(auth.get("oauth_scope") or ""),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": secrets.token_urlsafe(12),
    }
    sep = "&" if "?" in auth_url else "?"
    return auth_url + sep + urllib.parse.urlencode({k: v for k, v in params.items() if v})


def _http_form(url: str, fields: Dict[str, str], timeout: int,
               headers: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """POST 表单，返回 (响应体, 错误)。同步调用，超时有硬上限。"""
    if not url:
        return "", "Token 地址为空"
    body = urllib.parse.urlencode({k: str(v or "") for k, v in fields.items()}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json, application/x-www-form-urlencoded")
    for key, value in (headers or {}).items():
        req.add_header(key, str(value))
    try:
        with urllib.request.urlopen(req, timeout=max(1, min(int(timeout or 10), 60))) as res:
            return res.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        return "", f"HTTP {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)


def _parse_token(body: str) -> Tuple[Dict[str, Any], str]:
    body = (body or "").strip()
    if not body:
        return {}, "Token 响应为空"
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            return {}, "Token 响应不是 JSON 对象"
        return data, ""
    except Exception:  # noqa: BLE001
        pass
    try:
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        return {k: v[-1] for k, v in parsed.items()}, ""
    except Exception as exc:  # noqa: BLE001
        return {}, f"无法解析 Token 响应：{exc}"


def fetch_token(auth: Dict[str, Any], env: Dict[str, str], timeout: int = 10,
                refresh: bool = False) -> Tuple[Dict[str, Any], str]:
    """按 grant 换取 token。返回 (token 数据, 错误)。

    所有模板变量在发送前解析，token 只走 HTTPS/HTTP 明确给出的地址。
    """
    def resolve(v: Any) -> str:
        text = str(v or "")
        for name, value in (env or {}).items():
            text = text.replace("{{" + name + "}}", str(value))
        return text

    grant = resolve(auth.get("oauth_grant") or "client_credentials")
    token_url = resolve(auth.get("oauth_token_url") or "")
    fields: Dict[str, str] = {"grant_type": grant}
    if grant in ("client_credentials", "authorization_code"):
        fields["client_id"] = resolve(auth.get("oauth_client_id") or "")
        fields["client_secret"] = resolve(auth.get("oauth_client_secret") or "")
    elif grant == "password":
        fields.update(username=resolve(auth.get("oauth_username") or ""),
                      password=resolve(auth.get("oauth_password") or ""),
                      client_id=resolve(auth.get("oauth_client_id") or ""),
                      client_secret=resolve(auth.get("oauth_client_secret") or ""))
    scope = resolve(auth.get("oauth_scope") or "")
    if scope:
        fields["scope"] = scope
    if grant == "authorization_code":
        fields["code"] = resolve(auth.get("oauth_code") or "")
        fields["redirect_uri"] = resolve(auth.get("oauth_redirect_uri") or "")
        verifier, _ = pkce(resolve(auth.get("oauth_code_verifier") or ""))
        fields["code_verifier"] = verifier
    if refresh:
        fields["grant_type"] = "refresh_token"
        fields["refresh_token"] = resolve(auth.get("oauth_refresh_token") or "")
        fields.pop("code", None)
        fields.pop("code_verifier", None)

    body, err = _http_form(token_url, fields, timeout)
    if err:
        return {}, err
    data, err = _parse_token(body)
    if err:
        return {}, err
    if not data.get("access_token"):
        return {}, "Token 响应里没有 access_token"
    return data, ""


def apply_token(auth: Dict[str, Any], env: Dict[str, str],
                token: str) -> Dict[str, Any]:
    """把 token 归一化成现有认证管线认识的结构，复用 bearer / apikey 注入。"""
    placement = str(auth.get("oauth_token_placement") or "header")
    if placement == "query":
        return {"type": "apikey", "key": str(auth.get("oauth_token_key") or "access_token"),
                "value": token, "add_to": "query"}
    return {"type": "bearer", "token": token}


def effective(auth: Dict[str, Any], store, env: Dict[str, str],
              timeout: int = 10) -> Tuple[Dict[str, Any], str]:
    """给 ApiClient._effective_auth 用：拿缓存 / 刷新 / 新取 token。"""
    grant = str(auth.get("oauth_grant") or "client_credentials")
    # 手动模式：直接用用户粘贴的 token，绝不联网
    if grant == "implicit":
        token = str(auth.get("oauth_access_token") or "")
        for name, value in (env or {}).items():
            token = token.replace("{{" + name + "}}", str(value))
        if not token:
            return {"type": "none"}, "请先粘贴 Access Token"
        return apply_token(auth, env, token), ""

    entry = cached_token(auth, store, env)
    if entry is None:
        # 有 refresh token 就先刷新；否则重新换
        refresh = bool(auth.get("oauth_refresh_token")) and bool(entry is None and
                       auth.get("oauth_use_refresh", True))
        data, err = fetch_token(auth, env, timeout, refresh=refresh)
        if err:
            return {"type": "none"}, err
        save_token(auth, store, env, data)
        entry = cached_token(auth, store, env) or data
    return apply_token(auth, env, str(entry.get("access_token") or "")), ""
