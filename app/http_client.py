"""异步 HTTP 请求层（基于 QNetworkAccessManager）。

特性：非阻塞、可取消、超时、重定向策略、SSL 校验开关、Cookie 保持、
multipart 表单 / 文件上传、变量替换、耗时与体积统计。
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QByteArray, QElapsedTimer, QObject, QTimer, QUrl, QUrlQuery, pyqtSignal
from PyQt6.QtNetwork import (
    QHttpMultiPart,
    QHttpPart,
    QNetworkAccessManager,
    QNetworkCookie,
    QNetworkCookieJar,
    QNetworkRequest,
    QNetworkReply,
    QNetworkProxy,
    QSslConfiguration,
    QSslSocket,
)

from . import i18n
from .store import resolve_vars


def decompress_body(body: bytes, headers: List[Tuple[str, str]]) -> bytes:
    """解掉 Content-Encoding 压缩体。

    Qt 只在自己添加 Accept-Encoding 时才自动解压；用户手写了请求头、
    或服务器主动压缩时拿到的是一堆二进制，界面上就成了「乱码 / 全空白」。
    """
    if not body:
        return body
    enc = ""
    for k, v in headers:
        if k.lower() == "content-encoding":
            enc = v.lower().strip()
            break
    gz = body[:2] == b"\x1f\x8b"
    if not enc and not gz:
        return body
    try:
        if gz or "gzip" in enc or "x-gzip" in enc:
            import gzip

            return gzip.decompress(body)
        if "br" in enc:
            try:
                import brotli  # type: ignore

                return brotli.decompress(body)
            except Exception:  # noqa: BLE001
                return body
        if "deflate" in enc or "zlib" in enc:
            import zlib

            for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 32):
                try:
                    return zlib.decompress(body, wbits)
                except Exception:  # noqa: BLE001
                    continue
        return body
    except Exception:  # noqa: BLE001
        return body


@dataclass
class Response:
    status: int = 0
    reason: str = ""
    headers: List[Tuple[str, str]] = field(default_factory=list)
    body: bytes = b""
    elapsed: int = 0
    size: int = 0
    url: str = ""
    content_type: str = ""
    error: str = ""
    cookies: List[Dict[str, Any]] = field(default_factory=list)
    # 分段计时（毫秒）：none 表示该阶段未测到。ttfb/download 是真实测量，
    # 其余为基于总时间的估算，UI 上会标明「估算」。
    timing: Dict[str, int] = field(default_factory=dict)
    header_size: int = 0        # 响应头字节数（含状态行与结尾空行）
    request_size: int = 0       # 请求体字节数
    request_header_size: int = 0  # 请求头字节数（含请求行）

    def charset(self) -> str:
        return self.declared_charset() or "utf-8"

    def declared_charset(self) -> Optional[str]:
        """只在响应头 / meta 里真的写了 charset 时才返回，避免把 GBK 页面当 UTF-8 解。"""
        ct = self.content_type.lower()
        for part in ct.split(";"):
            part = part.strip()
            if part.startswith("charset="):
                return part.split("=", 1)[1].strip('"\' ') or None
        head = self.body[:2048].lower()
        if b"<meta" in head and b"charset" in head:
            i = head.find(b"charset")
            seg = head[i:i + 40].split(b"=", 1)[-1]
            for sep in (b'"', b"'", b">", b";", b" "):
                seg = seg.split(sep)[0]
            name = seg.strip()
            if name:
                return name.decode("latin-1", "ignore") or None
        return None

    def text(self) -> str:
        if not self.body:
            return ""
        declared = self.declared_charset()
        order = ([declared] if declared else []) + ["utf-8", "gb18030"]
        for enc in order:
            try:
                return self.body.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.body.decode("utf-8", errors="replace")

    def header(self, name: str) -> str:
        for k, v in self.headers:
            if k.lower() == name.lower():
                return v
        return ""

    @property
    def is_json(self) -> bool:
        ct = self.content_type.lower()
        if "json" in ct:
            return True
        head = self.body[:200].lstrip()[:1]
        return head in (b"{", b"[")

    @property
    def is_image(self) -> bool:
        ct = self.content_type.lower()
        if ct.startswith("image/"):
            return True
        # 有些服务端把图片当二进制返回，这里按文件头兜底识别
        head = self.body[:12]
        return (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff")
                or head.startswith(b"GIF8") or head.startswith(b"RIFF") and b"WEBP" in self.body[:16]
                or head.startswith(b"BM"))

    @property
    def kind(self) -> str:
        """内容大类：image / audio / video / pdf / json / text / binary。"""
        ct = self.content_type.lower()
        head = self.body[:4]
        if self.is_image:
            return "image"
        if ct.startswith("video/"):
            return "video"
        if ct.startswith("audio/") or ct == "application/ogg" or head == b"OggS" \
                or head == b"fLaC" or head[:3] == b"ID3":
            return "audio"
        if "pdf" in ct or head == b"%PDF":
            return "pdf"
        if self.is_json:
            return "json"
        if ct.startswith("text/") or "xml" in ct or "javascript" in ct or "html" in ct:
            return "text"
        return "binary"

    @property
    def ok(self) -> bool:
        return 0 < self.status < 400 and not self.error


class NoCookieJar(QNetworkCookieJar):
    """禁用 QNetworkAccessManager 自带的隐式 Cookie 罐。

    Qt 默认会把响应的 Set-Cookie 存起来、并在后续请求里自动带上，
    于是用户手写的 Cookie 头会被悄悄改写（表现是「我明明填了 Cookie，发出去却是别的」）。
    Ocelot 的 Cookie 由请求里的 Cookie 页显式管理，这里一律不读不写。
    """

    def cookiesForUrl(self, url):  # noqa: N802
        return []

    def setCookiesFromUrl(self, cookies, url):  # noqa: N802
        return False

    def insertCookie(self, cookie):  # noqa: N802
        return False


class ApiClient(QObject):
    started = pyqtSignal()
    finished = pyqtSignal(object)  # Response

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self.nam.setCookieJar(NoCookieJar(self.nam))
        self._reply: Optional[QNetworkReply] = None
        self._timer: Optional[QTimer] = None
        self._clock = QElapsedTimer()
        self._timeout = 30
        self._timed_out = False
        self._cancelled = False
        self._keepalive: List[Any] = []
        self._store = None
        self._request_size = 0
        self._request_header_size = 0
        self.scriptLogs = []          # 最近一次请求的脚本日志，供 UI 展示
        self._active_scripts: Dict[str, Any] = {}
        self._active_env_vars: Dict[str, str] = {}

    def set_store(self, store) -> None:
        """注入 Store：前置 / 后置脚本要读写环境变量。"""
        self._store = store

    # ------------------------------------------------------------ 请求脚本
    def _run_pre_script(self, req: Dict[str, Any], env_vars: Dict[str, str]) -> None:
        scripts = req.get("scripts") or {}
        source = scripts.get("pre") or ""
        if not source or self._store is None:
            return
        from .scripts import run_script

        result = run_script(source, self._store, req, env_vars=env_vars)
        self.scriptLogs = [("[pre] " + line) for line in result.logs]
        if result.error:
            self.scriptLogs.append("[pre] " + result.error)
        # 脚本可能新增/修改了环境变量：把快照同步给本次请求
        env_vars.update(self._store.env_vars())

    def _run_post_script(self, resp: "Response", env_vars: Dict[str, Any]) -> None:
        scripts = getattr(self, "_active_scripts", None) or {}
        source = scripts.get("post") or ""
        if not source or self._store is None:
            return
        from .scripts import run_script

        result = run_script(source, self._store,
                            {"method": "GET", "url": "", "headers": [], "params": [],
                             "body": {"raw": ""}}, res=resp, env_vars=env_vars)
        self.scriptLogs.extend(("[post] " + line) for line in result.logs)
        if result.error:
            self.scriptLogs.append("[post] " + result.error)

    # ------------------------------------------------------------ 代理
    def _configure_proxy(self, settings: Dict[str, Any], host: str = "") -> None:
        """auto：优先环境变量代理，其次系统代理；system：仅系统；off：直连。

        本地回环地址自动绕过代理，避免调试本地服务时被代理拦截。
        """
        mode = (settings.get("proxy_mode") or "auto").lower()
        try:
            # 用户显式选中的代理节点优先级最高（本地直连时 node_proxy 为空）
            node_proxy = settings.get("node_proxy") or ""
            if node_proxy:
                url = QUrl(node_proxy if "://" in node_proxy else "http://" + node_proxy)
                ptype = (QNetworkProxy.ProxyType.Socks5Proxy
                         if url.scheme().startswith("socks") else QNetworkProxy.ProxyType.HttpProxy)
                self.nam.setProxy(QNetworkProxy(ptype, url.host(), url.port() or 8080))
                return
            if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or host.endswith(".local"):
                self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
                return
            if mode == "off":
                self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
                return
            if mode == "system":
                self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy))
                return
            raw = ""
            for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
                raw = os.environ.get(key, "")
                if raw:
                    break
            if not raw:
                self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy))
                return
            url = QUrl(raw if "://" in raw else "http://" + raw)
            host = url.host()
            port = url.port() or (1080 if url.scheme().startswith("socks") else 8080)
            if not host:
                self.nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.DefaultProxy))
                return
            ptype = (QNetworkProxy.ProxyType.Socks5Proxy
                     if url.scheme().startswith("socks") else QNetworkProxy.ProxyType.HttpProxy)
            proxy = QNetworkProxy(ptype, host, port)
            if url.userName():
                proxy.setUser(url.userName())
                proxy.setPassword(url.password())
            self.nam.setProxy(proxy)
        except Exception:
            pass

    @property
    def busy(self) -> bool:
        return self._reply is not None or bool(getattr(self, "_relay", None)
                                               and self._relay.busy)

    # ------------------------------------------------------------ 公共 API
    def abort(self) -> None:
        if self._reply is not None:
            self._cancelled = True
            self._reply.abort()
        if getattr(self, "_relay", None) is not None:
            self._relay.abort()

    # ------------------------------------------------------------ 在线节点
    def _relay_client(self):
        if getattr(self, "_relay", None) is None:
            from .relay import RelayClient

            self._relay = RelayClient(self)
            self._relay.started.connect(self.started.emit)
            self._relay.finished.connect(self.finished.emit)
            self._relay.failed.connect(
                lambda msg: self.finished.emit(Response(error=msg)))
        return self._relay

    def _relay_payload(self, req, settings, env_vars) -> Dict[str, Any]:
        """把 Ocelot 的请求结构翻译成中继接口的 payload。"""
        raw_url = resolve_vars(req.get("url", ""), env_vars).strip()
        if not raw_url:
            raise ValueError("请求地址为空")
        if "://" not in raw_url:
            raw_url = "http://" + raw_url
        url = QUrl(raw_url)
        if not url.isValid() or not url.host():
            raise ValueError(i18n.trf("无效的 URL：{url}", url=raw_url))

        query = QUrlQuery(url)
        for row in req.get("params", []):
            if row.get("enabled", True) and row.get("key"):
                query.addQueryItem(resolve_vars(str(row["key"]), env_vars),
                                   resolve_vars(str(row.get("value", "")), env_vars))
        auth = req.get("auth") or {}
        if auth.get("type") == "apikey" and auth.get("add_to") == "query" and auth.get("key"):
            query.addQueryItem(resolve_vars(auth["key"], env_vars),
                               resolve_vars(auth.get("value", ""), env_vars))
        url.setQuery(query)

        headers: List[Dict[str, str]] = []
        cookie = ""
        content_type = ""
        for row in req.get("headers", []):
            if not row.get("enabled", True) or not row.get("key"):
                continue
            k = resolve_vars(str(row["key"]), env_vars)
            v = resolve_vars(str(row.get("value", "")), env_vars)
            if k.lower() == "cookie":
                cookie = v
            elif k.lower() == "content-type":
                content_type = v
                headers.append({"name": k, "value": v})
            else:
                headers.append({"name": k, "value": v})
        ua = (settings or {}).get("user_agent") or "Ocelot/1.0 (macOS)"
        headers.append({"name": "User-Agent", "value": str(ua)})
        cookie_pairs = [f"{resolve_vars(str(row['key']), env_vars)}="
                        f"{resolve_vars(str(row.get('value', '')), env_vars)}"
                        for row in req.get("cookies", [])
                        if row.get("enabled", True) and row.get("key")]
        if cookie_pairs:
            cookie = "; ".join(filter(None, ["; ".join(cookie_pairs), cookie]))
        if auth.get("type") == "bearer" and auth.get("token"):
            headers.append({"name": "Authorization",
                            "value": "Bearer " + resolve_vars(auth["token"], env_vars)})
        elif auth.get("type") == "basic":
            pair = f"{auth.get('username', '')}:{auth.get('password', '')}".encode()
            headers.append({"name": "Authorization",
                            "value": "Basic " + base64.b64encode(pair).decode()})
        elif auth.get("type") == "apikey" and auth.get("add_to") == "header" and auth.get("key"):
            headers.append({"name": resolve_vars(auth["key"], env_vars),
                            "value": resolve_vars(auth.get("value", ""), env_vars)})

        bdata = req.get("body") or {}
        mode = bdata.get("mode", "none")
        json_raw = ""
        params: List[Dict[str, str]] = []
        if mode == "json":
            json_raw = resolve_vars(bdata.get("raw", "") or "", env_vars)
            if not content_type:
                content_type = "application/json; charset=utf-8"
                headers.append({"name": "Content-Type", "value": content_type})
        elif mode in ("text", "xml"):
            # 中继接口只接受 text / json 字符串，文本按 JSON 字段外的 body 传不了，
            # 统一塞进 json 字段并让服务端按对应 Content-Type 转发。
            json_raw = resolve_vars(bdata.get("raw", "") or "", env_vars)
            if not content_type:
                content_type = ("application/xml; charset=utf-8" if mode == "xml"
                                else "text/plain; charset=utf-8")
                headers.append({"name": "Content-Type", "value": content_type})
        elif mode == "urlencoded":
            for row in bdata.get("form", []):
                if row.get("enabled", True) and row.get("key") \
                        and row.get("type") != "file":
                    params.append({"name": resolve_vars(str(row["key"]), env_vars),
                                   "value": resolve_vars(str(row.get("value", "")), env_vars)})
        elif mode in ("form", "binary"):
            raise ValueError("在线节点不支持文件上传 / multipart，请切回本地直连或自建代理")

        return {
            "node": settings["relay_node"].get("unid", ""),
            "ip_version": 6 if settings["relay_node"].get("v6") else 4,
            "url": url.toString(),
            "method": (req.get("method") or "GET").upper(),
            "params": params,
            "json": json_raw,
            "headers": headers,
            "content_type": content_type,
            "cookie": cookie,
        }

    def send(self, req: Dict[str, Any], settings: Optional[Dict[str, Any]] = None,
             env_vars: Optional[Dict[str, str]] = None) -> None:
        settings = settings or {}
        env_vars = env_vars or {}
        self.abort()
        self._timed_out = False
        self._cancelled = False
        self._keepalive = []
        self.scriptLogs = []

        # 前置脚本：在中继分支之前执行，覆盖所有发送路径
        self._active_scripts = req.get("scripts") or {}
        self._active_env_vars = dict(env_vars)
        self._run_pre_script(req, env_vars)

        if settings.get("relay_node"):
            try:
                payload = self._relay_payload(req, settings, env_vars)
            except ValueError as exc:
                self.finished.emit(Response(error=str(exc)))
                return
            self._relay_client().send(payload, int(settings.get("timeout", 30) or 30))
            return

        raw_url = resolve_vars(req.get("url", ""), env_vars).strip()
        if not raw_url:
            self.finished.emit(Response(error="请求地址为空"))
            return
        if "://" not in raw_url:
            raw_url = "http://" + raw_url
        url = QUrl(raw_url)
        if not url.isValid() or not url.host():
            self.finished.emit(Response(error=i18n.trf("无效的 URL：{url}", url=raw_url)))
            return

        # 查询参数
        query = QUrlQuery(url)
        for row in req.get("params", []):
            if not row.get("enabled", True) or not row.get("key"):
                continue
            if row.get("type") == "file":
                continue          # 文件只能走 multipart 请求体，URL 参数里放不了
            query.addQueryItem(
                resolve_vars(str(row["key"]), env_vars),
                resolve_vars(str(row.get("value", "")), env_vars),
            )

        auth = req.get("auth") or {}
        if auth.get("type") == "apikey" and auth.get("add_to") == "query" and auth.get("key"):
            query.addQueryItem(resolve_vars(auth["key"], env_vars),
                               resolve_vars(auth.get("value", ""), env_vars))
        url.setQuery(query)

        nreq = QNetworkRequest(url)
        nreq.setAttribute(QNetworkRequest.Attribute.Http2AllowedAttribute, True)

        # 请求头
        has_ct = False
        for row in req.get("headers", []):
            if not row.get("enabled", True) or not row.get("key"):
                continue
            k = resolve_vars(str(row["key"]), env_vars)
            v = resolve_vars(str(row.get("value", "")), env_vars)
            try:
                nreq.setRawHeader(k.encode("utf-8"), v.encode("utf-8"))
            except Exception:
                continue
            if k.lower() == "content-type":
                has_ct = True

        if not nreq.rawHeader(b"User-Agent"):
            ua = (settings or {}).get("user_agent") or "Ocelot/1.0 (macOS)"
            nreq.setRawHeader(b"User-Agent", str(ua).encode("utf-8"))
        if not nreq.rawHeader(b"Accept"):
            nreq.setRawHeader(b"Accept", b"*/*")

        # 认证
        if auth.get("type") == "bearer" and auth.get("token"):
            token = resolve_vars(auth["token"], env_vars)
            nreq.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        elif auth.get("type") == "basic":
            pair = f"{auth.get('username', '')}:{auth.get('password', '')}".encode("utf-8")
            nreq.setRawHeader(b"Authorization", b"Basic " + base64.b64encode(pair))
        elif auth.get("type") == "apikey" and auth.get("add_to") == "header" and auth.get("key"):
            nreq.setRawHeader(auth["key"].encode("utf-8"),
                              resolve_vars(auth.get("value", ""), env_vars).encode("utf-8"))

        # Cookie 表：与手写的 Cookie 头合并（表在前、原头在后），两边都保留
        cookie_pairs = [f"{resolve_vars(str(row['key']), env_vars)}="
                        f"{resolve_vars(str(row.get('value', '')), env_vars)}"
                        for row in req.get("cookies", [])
                        if row.get("enabled", True) and row.get("key")]
        if cookie_pairs:
            merged = "; ".join(cookie_pairs)
            current = bytes(nreq.rawHeader(b"Cookie")).decode("utf-8", "replace").strip()
            if current:
                merged = f"{merged}; {current}"
            nreq.setRawHeader(b"Cookie", merged.encode("utf-8"))

        # 请求体
        payload = QByteArray()
        multipart: Optional[QHttpMultiPart] = None
        bdata = req.get("body") or {}
        mode = bdata.get("mode", "none")
        if mode == "json":
            text = resolve_vars(bdata.get("raw", "") or "", env_vars)
            payload = QByteArray(text.encode("utf-8"))
            if not has_ct:
                nreq.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                               "application/json; charset=utf-8")
        elif mode in ("text", "xml"):
            text = resolve_vars(bdata.get("raw", "") or "", env_vars)
            payload = QByteArray(text.encode("utf-8"))
            if not has_ct:
                nreq.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                               ("application/xml; charset=utf-8" if mode == "xml"
                                else "text/plain; charset=utf-8"))
        elif mode == "urlencoded":
            q = QUrlQuery()
            for row in bdata.get("form", []):
                if row.get("enabled", True) and row.get("key") \
                        and row.get("type") != "file":
                    q.addQueryItem(resolve_vars(str(row["key"]), env_vars),
                                   resolve_vars(str(row.get("value", "")), env_vars))
            payload = QByteArray(q.query(QUrl.ComponentFormattingOption.FullyEncoded).encode("utf-8"))
            if not has_ct:
                nreq.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                               "application/x-www-form-urlencoded")
        elif mode == "form":
            multipart = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)
            for row in bdata.get("form", []):
                if not row.get("enabled", True) or not row.get("key"):
                    continue
                key = resolve_vars(str(row["key"]), env_vars)
                val = resolve_vars(str(row.get("value", "")), env_vars)
                is_file = row.get("type") == "file" or val.startswith("@")
                path = val[1:].strip() if val.startswith("@") else val.strip()
                part = QHttpPart()
                if is_file:
                    path = os.path.expanduser(path)
                    if os.path.exists(path):
                        from PyQt6.QtCore import QFile, QIODevice
                        f = QFile(path)
                        if f.open(QIODevice.OpenModeFlag.ReadOnly):
                            part.setHeader(
                                QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                                f'form-data; name="{key}"; filename="{os.path.basename(path)}"',
                            )
                            part.setBodyDevice(f)
                            f.setParent(multipart)
                        else:
                            continue
                    else:
                        part.setHeader(
                            QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                            f'form-data; name="{key}"')
                        part.setBody(val.encode("utf-8"))
                else:
                    part.setHeader(QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                                   f'form-data; name="{key}"')
                    part.setBody(val.encode("utf-8"))
                multipart.append(part)
        elif mode == "binary":
            path = bdata.get("file") or ""
            if path and os.path.exists(path):
                try:
                    with open(path, "rb") as fh:
                        payload = QByteArray(fh.read())
                except Exception as exc:
                    self.finished.emit(Response(error=i18n.trf("读取文件失败：{err}", err=exc)))
                    return
                if not has_ct:
                    nreq.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,
                                   "application/octet-stream")
            else:
                self.finished.emit(Response(error="请选择一个有效的二进制文件"))
                return

        # 网络策略
        self._timeout = int(settings.get("timeout", 30) or 0)
        try:
            policy = (QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
                      if settings.get("follow_redirects", True)
                      else QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            self.nam.setRedirectPolicy(policy)
        except Exception:
            pass
        if not settings.get("verify_ssl", True):
            try:
                cfg = QSslConfiguration.defaultConfiguration()
                cfg.setPeerVerifyMode(QSslSocket.PeerVerifyMode.VerifyNone)
                nreq.setSslConfiguration(cfg)
            except Exception:
                pass

        self._configure_proxy(settings, url.host())
        method = (req.get("method") or "GET").upper()
        # 请求体积：用真正发出去的 QNetworkRequest 原始头 + 请求行来算，
        # 不再拿界面上的字符串猜（那样漏掉默认注入的 UA / Accept / Cookie）。
        req_header_bytes = len(method.encode("utf-8")) + 1 + len(
            QUrl(raw_url).path(QUrl.ComponentFormattingOption.FullyEncoded).encode("utf-8")) + 1 + 8
        for name in nreq.rawHeaderList():
            req_header_bytes += len(bytes(name)) + len(bytes(nreq.rawHeader(name))) + 4
        self._request_size = int(payload.size()) if not isinstance(payload, type(None)) else 0
        self._request_header_size = req_header_bytes

        self._clock.start()
        try:
            if multipart is not None:
                reply = self.nam.sendCustomRequest(nreq, method.encode(), multipart)
                multipart.setParent(reply)
            else:
                reply = self.nam.sendCustomRequest(nreq, method.encode(), payload)
        except Exception as exc:
            self.finished.emit(Response(error=i18n.trf("请求构造失败：{err}", err=exc)))
            return

        self._reply = reply
        self._ttfb = 0
        reply.metaDataChanged.connect(self._on_meta)
        reply.finished.connect(self._on_finished)
        if self._timeout > 0:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._on_timeout)
            self._timer.start(self._timeout * 1000)
        self.started.emit()

    # ------------------------------------------------------------ 内部
    def _on_meta(self) -> None:
        # 收到响应头 = TTFB（含 DNS + TCP + TLS + 服务端处理）。只记第一次。
        if not self._ttfb:
            self._ttfb = self._clock.elapsed()

    def _on_timeout(self) -> None:
        if self._reply is not None:
            self._timed_out = True
            self._reply.abort()

    def _on_finished(self) -> None:
        reply = self.sender()
        if reply is None or reply is not self._reply:
            # 旧请求被新请求顶掉时，它的 finished 还是会来。这时候如果照着
            # self._reply 往下走，就会把「新请求」当成结束、把响应记错，
            # 新请求的响应反而再也等不到（界面一直转圈）。
            if reply is not None:
                try:
                    reply.deleteLater()
                except RuntimeError:
                    pass
            return
        self._reply = None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        elapsed = self._clock.elapsed()
        err = reply.error()
        body = bytes(reply.readAll())
        status = int(reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0)
        reason = str(reply.attribute(QNetworkRequest.Attribute.HttpReasonPhraseAttribute) or "")
        final_url = reply.url().toString()

        headers: List[Tuple[str, str]] = []
        try:
            for k, v in reply.rawHeaderPairs():
                headers.append((bytes(k).decode("latin-1"), bytes(v).decode("latin-1")))
        except Exception:
            for k in reply.rawHeaderList():
                headers.append((bytes(k).decode("latin-1"),
                                bytes(reply.rawHeader(k)).decode("latin-1")))

        ct = ""
        for k, v in headers:
            if k.lower() == "content-type":
                ct = v
                break

        cookies: List[Dict[str, Any]] = []
        for k, v in headers:
            if k.lower() == "set-cookie":
                for c in QNetworkCookie.parseCookies(QByteArray(v.encode("latin-1"))):
                    cookies.append({
                        "name": bytes(c.name()).decode("utf-8", "replace"),
                        "value": bytes(c.value()).decode("utf-8", "replace"),
                        "domain": c.domain(),
                        "path": c.path(),
                        "expires": c.expirationDate().toString("yyyy-MM-dd HH:mm") if not c.expirationDate().isNull() else "session",
                        "secure": c.isSecure(),
                        "http_only": c.isHttpOnly(),
                    })

        error = ""
        if err != QNetworkReply.NetworkError.NoError and status == 0:
            if self._timed_out:
                error = i18n.trf("请求超时（{n}s）", n=self._timeout)
            elif self._cancelled:
                error = "请求已取消"
            else:
                error = reply.errorString()

        body = decompress_body(body, headers)

        # 分段计时：TTFB 与下载是真实测量；前置阶段按 TTFB 比例拆分并标注为估算。
        ttfb = int(getattr(self, "_ttfb", 0) or 0)
        if ttfb > elapsed:
            ttfb = elapsed
        download = max(0, elapsed - ttfb)
        pre = max(0, ttfb - 3)
        timing = {
            "prepare": 3 if elapsed else 0,
            "dns": round(pre * 0.10),
            "tcp": round(pre * 0.08),
            "ssl": round(pre * 0.09) if final_url.startswith("https") else 0,
            "ttfb": ttfb,
            "download": download,
            "process": 0,
        }
        # 头部字节数：加上状态行与结尾空行，才是线上真实开销（原来只算 key+value+4，
        # 少了「HTTP/1.1 200 OK\r\n」和结尾的 \r\n，显示总是偏小）。
        http_version = "HTTP/1.1"
        status_line = f"{http_version} {status} {reason}\r\n"
        header_size = (len(status_line.encode("latin-1", "replace"))
                       + sum(len(k.encode("latin-1", "replace")) +
                             len(v.encode("latin-1", "replace")) + 4 for k, v in headers)
                       + 2)

        resp = Response(
            status=status, reason=reason, headers=headers, body=body,
            elapsed=elapsed, size=len(body), url=final_url, content_type=ct,
            error=error, cookies=cookies, timing=timing, header_size=header_size,
            request_size=getattr(self, "_request_size", 0),
            request_header_size=getattr(self, "_request_header_size", 0),
        )
        # 后置脚本可改写响应（status / body / headers）或写环境变量
        try:
            self._run_post_script(resp, dict(self._active_env_vars or {}))
        except Exception:  # noqa: BLE001 — 脚本失败不能影响响应展示
            pass
        reply.deleteLater()
        self.finished.emit(resp)
