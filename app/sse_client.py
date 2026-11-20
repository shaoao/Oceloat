"""SSE（Server-Sent Events）连接层：只收不发的一条长连接。

为什么用 QNetworkAccessManager 而不是再开一个线程：
SSE 就是「HTTP 响应一直不结束，服务端一行行往下写」，QNetworkReply 的
readyRead 正好是一条流式管道 —— 不用自己写 socket 循环、不会阻塞界面，
断线、超时、TLS 校验也都交给 Qt。

协议解析按 WHATWG 规范来：
    event: 事件名（缺省是 message）
    data:  数据，可以多行，最终用 \\n 拼起来
    id:    事件 id，重连时作为 Last-Event-ID 发回去
    retry: 服务端建议的重连间隔（毫秒）
    以 : 开头的行是注释（很多服务端拿它做心跳）
空行代表一个事件结束。这条连接不会发送任何数据，所以 send_* 都是空操作。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
    QSslConfiguration,
)

STATE_IDLE = "idle"
STATE_CONNECTING = "connecting"
STATE_OPEN = "open"
STATE_CLOSING = "closing"
STATE_CLOSED = "closed"

MAX_FRAME_BYTES = 4 * 1024 * 1024          # 单个事件别超过 4MB
LINE_LIMIT = 64 * 1024


@dataclass
class SseFrame:
    """一条 SSE 日志：事件、注释、连接状态都用同一个结构，方便统一渲染。"""

    dir: str = "in"                 # in / sys
    kind: str = "message"           # 事件名；sys 时是 open / close / error / retry
    data: bytes = b""
    at: float = field(default_factory=time.time)
    size: int = 0
    event_id: str = ""
    retry: int = 0

    def text(self) -> str:
        return self.data.decode("utf-8", "replace")

    def preview(self, limit: int = 400) -> str:
        text = self.text()
        return text if len(text) <= limit else text[:limit] + "…"

    def inline_preview(self, limit: int = 400) -> str:
        text = self.text().strip()
        if text[:1] in ("{", "["):
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False,
                                  separators=(",", ":"))
            except Exception:      # noqa: BLE001
                pass
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return "(空事件)"
        return text if len(text) <= limit else text[:limit] + "…"


def sse_url(raw: str) -> str:
    """SSE 走普通 HTTP，所以 http(s) 地址直接用；没写协议就补 http://。"""
    text = (raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low.startswith(("http://", "https://")):
        return text
    if low.startswith("ws://"):
        return "http://" + text[len("ws://"):]
    if low.startswith("wss://"):
        return "https://" + text[len("wss://"):]
    if "://" in text:
        return text
    return "http://" + text


class SseClient(QObject):
    """一条 SSE 连接。接口与 WsClient 对齐，主窗口那套状态机可以直接复用。"""

    stateChanged = pyqtSignal(str)
    opened = pyqtSignal(str)            # 服务端 content-type（可能为空）
    closed = pyqtSignal(int, str)       # code, reason
    failed = pyqtSignal(str)
    frame = pyqtSignal(object)
    retrying = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mgr = QNetworkAccessManager(self)
        self._reply: Optional[QNetworkReply] = None
        self._buf = ""
        self._stopped = True
        self._auto = True
        self._attempt = 0
        self._opened_at = 0.0
        self._bytes = 0
        self._events = 0
        self._last_id = ""
        self._retry_ms = 1500
        self._url = ""
        self._state = STATE_IDLE
        # 握手结果：SSE 直接复用 HTTP 响应，状态码 / Content-Type / 响应头
        # 是排查「为什么一条事件都不来」的唯一线索（401、500、被代理拦）。
        self.status = 0
        self.content_type = ""
        self.headers: Dict[str, str] = {}
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._reconnect)

    # -------------------------------------------------- 状态
    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == STATE_OPEN

    @property
    def busy(self) -> bool:
        return self._state in (STATE_OPEN, STATE_CONNECTING, STATE_CLOSING)

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def stats(self) -> Dict[str, Any]:
        return {"uptime": max(0.0, time.time() - self._opened_at) if self._opened_at else 0.0,
                "bytes_in": self._bytes, "events": self._events,
                "attempt": self._attempt, "status": self.status,
                "content_type": self.content_type}

    # -------------------------------------------------- 连接
    def connect_to(self, url: str, headers: Optional[List[tuple]] = None,
                   last_event_id: str = "", auto_reconnect: bool = True,
                   verify_ssl: bool = True, retry_ms: int = 1500) -> bool:
        self.disconnect_ws()
        target = sse_url(url)
        if not target:
            return False
        self._url = target
        self._headers = list(headers or [])
        self._verify = bool(verify_ssl)
        self._auto = bool(auto_reconnect)
        self._last_id = last_event_id or ""
        self._retry_ms = max(300, int(retry_ms or 1500))
        self._attempt = 0
        self._stopped = False
        self._buf = ""
        self._bytes = 0
        self._events = 0
        self.status = 0
        self.content_type = ""
        self.headers = {}
        self._open()
        return True

    def _open(self) -> None:
        qurl = QUrl(self._url)
        if not qurl.isValid():
            self._stopped = True
            self._set_state(STATE_IDLE)
            self.failed.emit("地址不合法")
            return
        req = QNetworkRequest(qurl)
        req.setRawHeader(b"Accept", b"text/event-stream")
        req.setRawHeader(b"Cache-Control", b"no-cache")
        req.setRawHeader(b"Accept-Encoding", b"identity")
        if self._last_id:
            req.setRawHeader(b"Last-Event-ID", self._last_id.encode("utf-8"))
        for key, value in getattr(self, "_headers", []):
            k = str(key or "").strip()
            if k:
                req.setRawHeader(k.encode("utf-8"), str(value or "").encode("utf-8"))
        try:
            conf = QSslConfiguration.defaultConfiguration()
            if not getattr(self, "_verify", True):
                conf.setPeerVerifyMode(QSslConfiguration.PeerVerifyMode.VerifyNone)
            req.setSslConfiguration(conf)
        except Exception:          # noqa: BLE001 — 老平台没有 SSL 配置也不影响 HTTP
            pass
        self._set_state(STATE_CONNECTING)
        self._reply = self._mgr.get(req)
        self._reply.readyRead.connect(self._on_ready)
        self._reply.finished.connect(self._on_finished)
        self._reply.errorOccurred.connect(self._on_error)

    def _stop_reply(self) -> None:
        """收掉当前这条响应（不触发自动重连的判断逻辑）。"""
        reply, self._reply = self._reply, None
        if reply is not None:
            try:
                reply.finished.disconnect()
            except TypeError:
                pass
            try:
                reply.abort()
                reply.deleteLater()
            except RuntimeError:
                pass
        self._opened_at = 0.0
        self._set_state(STATE_IDLE)

    def _reconnect(self) -> None:
        if self._stopped:
            return
        self._attempt += 1
        self._open()

    def disconnect_ws(self) -> None:
        """断开（不自动重连）。名字与 WsClient 一致，主窗口不用分支。"""
        self._stopped = True
        self._retry_timer.stop()
        reply, self._reply = self._reply, None
        if reply is not None:
            try:
                reply.abort()
                reply.deleteLater()
            except RuntimeError:
                pass
        if self._state in (STATE_OPEN, STATE_CONNECTING):
            self._set_state(STATE_CLOSING)
        self._opened_at = 0.0
        self._set_state(STATE_IDLE)

    def abort(self) -> None:
        self.disconnect_ws()

    # -------------------------------------------------- 收数据
    def _on_ready(self) -> None:
        reply = self._reply
        if reply is None:
            return
        raw = bytes(reply.readAll())
        if not raw:
            return
        self._bytes += len(raw)
        if self._state == STATE_CONNECTING:
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
            ctype = bytes(reply.rawHeader(b"Content-Type")).decode("latin-1", "ignore")
            self.status = int(status or 0)
            self.content_type = ctype.split(";")[0].strip()
            self.headers = {bytes(k).decode("latin-1", "ignore"):
                            bytes(v).decode("latin-1", "ignore")
                            for k, v in reply.rawHeaderPairs()}
            if status and (status >= 400 or status not in (200, 201, 204, 206)):
                # 失败响应往往是一段 JSON / HTML 错误说明：把它当一条系统日志
                # 吐出来，用户才知道到底是 401 还是路径写错，而不是一句「失败」。
                body = raw[:8192].decode("utf-8", "replace").strip()
                msg = f"HTTP {status}"
                if body:
                    msg += " · " + re.sub(r"\s+", " ", body)[:600]
                self._emit(SseFrame(dir="sys", kind="error", data=msg.encode("utf-8"),
                                    size=len(msg.encode("utf-8"))))
                self.failed.emit(f"服务端返回 {status}")
                self._stop_reply()
                return
            self._opened_at = time.time()
            self._attempt = 0
            self._set_state(STATE_OPEN)
            self.opened.emit(self.content_type)
        self._buf += raw.decode("utf-8", "replace")
        self._drain()

    def _drain(self) -> None:
        # 统一换行：\r\n / \r 都按 \n 处理，然后按行切；最后一行可能是半句，留着
        text = self._buf.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        self._buf = lines.pop() if lines else ""
        if len(self._buf) > LINE_LIMIT:
            self._buf = ""
        event, data, eid, retry = "", [], "", 0
        for line in lines:
            if not line:
                self._dispatch(event, data, eid, retry)
                event, data, eid, retry = "", [], "", 0
                continue
            if line.startswith(":"):
                # 注释行：心跳 / 保活。留着当一条轻量日志，用户能看出「连接还活着」
                self._emit(SseFrame(dir="sys", kind="ping", data=b"",
                                    size=len(line), event_id=""))
                continue
            key, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if key == "data":
                data.append(value)
            elif key == "event":
                event = value.strip()
            elif key == "id":
                if "\x00" not in value:
                    eid = value
            elif key == "retry":
                try:
                    retry = max(300, int(value.strip()))
                except ValueError:
                    retry = 0
        # 行末没有空行时先攒着（服务端可能把事件拆成两次 write）

    def _dispatch(self, event: str, data: List[str], eid: str, retry: int) -> None:
        if not data and not event and not eid:
            return
        payload = "\n".join(data)
        self._events += 1
        if eid:
            self._last_id = eid
        if retry:
            self._retry_ms = retry
        kind = (event or "message").strip() or "message"
        self._emit(SseFrame(dir="in", kind=kind, data=payload.encode("utf-8"),
                            size=len(payload.encode("utf-8")), event_id=eid, retry=retry))

    def _emit(self, frame: SseFrame) -> None:
        if frame.size > MAX_FRAME_BYTES:
            frame.data = frame.data[:MAX_FRAME_BYTES]
            frame.size = MAX_FRAME_BYTES
        self.frame.emit(frame)

    # -------------------------------------------------- 断开 / 失败
    def _on_error(self, _code) -> None:
        reply = self._reply
        if reply is None or self._stopped:
            return
        msg = reply.errorString() or "连接失败"
        self.failed.emit(msg)

    def _on_finished(self) -> None:
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.deleteLater()
        was_open = self._opened_at > 0
        self._opened_at = 0.0
        if self._stopped:
            self._set_state(STATE_IDLE)
            return
        if self._auto:
            delay = min(15_000, self._retry_ms * (2 ** min(self._attempt, 4)))
            self._set_state(STATE_CONNECTING)
            # 只在真正开始等待时报一次；_reconnect 里再报一次会让「第 n 次重连」
            # 一秒钟跳两格，次数永远对不上。
            self.retrying.emit(self._attempt + 1, delay)
            self._retry_timer.start(delay)
            return
        self._set_state(STATE_IDLE)
        self.closed.emit(0 if was_open else 1006, "连接已断开")
