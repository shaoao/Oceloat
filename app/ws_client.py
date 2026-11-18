"""WebSocket 连接层（基于 QWebSocket，纯事件驱动，不阻塞界面）。

设计要点：
- 一个客户端只维护一条连接；连上后用信号把每一帧抛给主窗口，日志由上层保存。
- 握手头、认证、子协议都在这里拼好；地址支持 ws:// wss:// 以及 http(s):// 自动改写。
- 心跳用协议自带的 ping/pong，延迟就是真实往返时间；自动重连按指数退避，最长 15 秒。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QByteArray, QObject, QTimer, QUrl, pyqtSignal

try:                                            # 极少数精简版 PyQt6 不带 WebSockets
    from PyQt6.QtWebSockets import QWebSocket
except Exception:                               # noqa: BLE001
    QWebSocket = None                            # type: ignore[assignment]

from PyQt6.QtNetwork import QNetworkRequest

STATE_IDLE = "idle"
STATE_CONNECTING = "connecting"
STATE_OPEN = "open"
STATE_CLOSING = "closing"
STATE_CLOSED = "closed"


def ws_url(raw: str) -> str:
    """把用户输入的地址规整成 ws(s)://。

    很多人会直接粘 http(s) 地址（或根本不写协议），这里统一改写而不是报错。
    """
    text = (raw or "").strip()
    if not text:
        return ""
    low = text.lower()
    if low.startswith("ws://") or low.startswith("wss://"):
        return text
    if low.startswith("https://"):
        return "wss://" + text[len("https://"):]
    if low.startswith("http://"):
        return "ws://" + text[len("http://"):]
    if "://" in text:
        return text
    return "ws://" + text


def frame_kind(data: bytes, binary: bool) -> str:
    if binary:
        return "binary"
    try:
        text = data.decode("utf-8", "strict").strip()
    except Exception:                            # noqa: BLE001
        return "text"
    if text[:1] in ("{", "["):
        try:
            json.loads(text)
            return "json"
        except Exception:                        # noqa: BLE001
            return "text"
    return "text"


@dataclass
class WsFrame:
    """一条日志记录：收发帧、连接事件、错误都走同一个结构，方便统一渲染。"""

    dir: str = "in"            # in / out / sys
    kind: str = "text"         # text / json / binary / ping / pong / open / close / error
    data: bytes = b""
    at: float = field(default_factory=time.time)
    size: int = 0

    def text(self) -> str:
        return self.data.decode("utf-8", "replace")

    def preview(self, limit: int = 400) -> str:
        if self.kind == "binary":
            return f"<{self.size} bytes> " + self.data[:48].hex(" ")
        text = self.text()
        return text if len(text) <= limit else text[:limit] + "…"


class WsClient(QObject):
    """一条 WebSocket 连接。"""

    stateChanged = pyqtSignal(str)
    opened = pyqtSignal(str)            # 协商到的子协议（可能为空）
    closed = pyqtSignal(int, str)       # code, reason
    failed = pyqtSignal(str)
    frame = pyqtSignal(object)          # WsFrame
    ponged = pyqtSignal(int)            # 往返延迟 ms
    retrying = pyqtSignal(int, int)     # attempt, delay_ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = STATE_IDLE
        self._manual = False
        self._attempt = 0
        self._auto_reconnect = False
        self._ping_secs = 0
        self._url = ""
        self._headers: List[Tuple[str, str]] = []
        self._protocol = ""
        self.bytes_in = 0
        self.bytes_out = 0
        self.frames_in = 0
        self.frames_out = 0
        self.opened_at = 0.0
        self.latency = 0
        self._claimed = False       # 「已连上过」：用于区分「连不上」和「连上后断开」

        self._sock: Optional["QWebSocket"] = None
        self._ping_timer = QTimer(self)
        self._ping_timer.timeout.connect(self._ping)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._do_retry)

    # -------------------------------------------------- 状态
    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == STATE_OPEN and self._sock is not None

    @property
    def busy(self) -> bool:
        return self._state in (STATE_CONNECTING, STATE_OPEN, STATE_CLOSING)

    def _set_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        self.stateChanged.emit(state)

    def _ensure_socket(self) -> "QWebSocket":
        if self._sock is not None:
            return self._sock
        if QWebSocket is None:
            raise RuntimeError("当前环境缺少 QtWebSockets 模块")
        sock = QWebSocket()
        sock.connected.connect(self._on_connected)
        sock.disconnected.connect(self._on_disconnected)
        sock.textMessageReceived.connect(self._on_text)
        sock.binaryMessageReceived.connect(self._on_binary)
        sock.errorOccurred.connect(self._on_error)
        sock.pong.connect(self._on_pong)
        try:
            sock.sslErrors.connect(self._on_ssl_errors)
        except Exception:                        # noqa: BLE001
            pass
        self._sock = sock
        return sock

    # -------------------------------------------------- 连接
    def connect_to(self, url: str, headers: Optional[List[Tuple[str, str]]] = None,
                   protocol: str = "", *, auto_reconnect: bool = False,
                   ping_secs: int = 0, verify_ssl: bool = True) -> bool:
        if QWebSocket is None:
            self.failed.emit("当前环境缺少 QtWebSockets 模块，无法建立 WebSocket 连接")
            return False
        target = ws_url(url)
        if not target:
            self.failed.emit("请先填写 ws:// 或 wss:// 地址")
            return False
        self._sock = None                        # 每次重连都换一条干净的连接
        sock = self._ensure_socket()
        self._url = target
        self._headers = [(str(k), str(v)) for k, v in (headers or []) if str(k).strip()]
        self._protocol = (protocol or "").strip()
        self._auto_reconnect = bool(auto_reconnect)
        self._ping_secs = max(0, int(ping_secs or 0))
        self._manual = False
        self._attempt = 0
        self._claimed = False
        self._verify = bool(verify_ssl)
        self.bytes_in = self.bytes_out = self.frames_in = self.frames_out = 0
        self.latency = 0

        req = QNetworkRequest(QUrl(target))
        for key, value in self._headers:
            try:
                req.setRawHeader(key.encode("utf-8"), value.encode("utf-8"))
            except Exception:                    # noqa: BLE001
                continue
        if self._protocol:
            try:
                req.setRawHeader(b"Sec-WebSocket-Protocol",
                                 self._protocol.encode("utf-8"))
            except Exception:                    # noqa: BLE001
                pass
        self._set_state(STATE_CONNECTING)
        self._emit(WsFrame("sys", "open", f"正在连接 {target}".encode("utf-8")))
        sock.open(req)
        return True

    def _on_connected(self) -> None:
        self._claimed = True
        self._attempt = 0
        self.opened_at = time.time()
        self._set_state(STATE_OPEN)
        proto = ""
        try:
            proto = self._sock.selectedProtocol() if self._sock is not None else ""
        except Exception:                        # noqa: BLE001
            proto = ""
        self.opened.emit(proto)
        self._emit(WsFrame("sys", "open", b"", size=0))
        if self._ping_secs:
            self._ping_timer.start(self._ping_secs * 1000)

    def _on_disconnected(self) -> None:
        self._ping_timer.stop()
        code, reason = 1006, ""
        try:
            if self._sock is not None:
                code = int(self._sock.closeCode())
                reason = self._sock.closeReason()
        except Exception:                        # noqa: BLE001
            pass
        self._set_state(STATE_CLOSED)
        self.closed.emit(code, reason)
        self._emit(WsFrame("sys", "close", f"{code} {reason}".strip().encode("utf-8")))
        if self._auto_reconnect and not self._manual:
            self._schedule_retry()

    def _on_error(self, _err) -> None:
        msg = ""
        try:
            msg = self._sock.errorString() if self._sock is not None else ""
        except Exception:                        # noqa: BLE001
            msg = ""
        msg = msg or "连接失败"
        self._emit(WsFrame("sys", "error", msg.encode("utf-8")))
        if self._state == STATE_CONNECTING:
            self._set_state(STATE_CLOSED)
            self.failed.emit(msg)
            if self._auto_reconnect and not self._manual:
                self._schedule_retry()

    def _on_ssl_errors(self, errors) -> None:
        if getattr(self, "_verify", True):
            msgs = "; ".join(getattr(e, "errorString", lambda: str(e))() for e in errors)
            self.failed.emit(f"TLS 证书校验失败：{msgs}（可在设置里关闭「校验 SSL 证书」）")
            return
        try:
            if self._sock is not None:
                self._sock.ignoreSslErrors()
        except Exception:                        # noqa: BLE001
            pass

    # -------------------------------------------------- 重连
    def _schedule_retry(self) -> None:
        self._attempt += 1
        delay = int(min(15.0, 0.6 * (2 ** min(self._attempt, 5))) * 1000)
        self.retrying.emit(self._attempt, delay)
        self._emit(WsFrame("sys", "error",
                           f"连接已断开，{delay / 1000:.1f} 秒后自动重连（第 {self._attempt} 次）"
                           .encode("utf-8")))
        self._retry_timer.start(delay)

    def _do_retry(self) -> None:
        if self._manual or not self._auto_reconnect:
            return
        self.connect_to(self._url, self._headers, self._protocol,
                        auto_reconnect=True, ping_secs=self._ping_secs,
                        verify_ssl=getattr(self, "_verify", True))
        # connect_to 会把 attempt 归零，重连次数用单独计数体现
        self._attempt = max(1, self._attempt)

    # -------------------------------------------------- 收发
    def send_text(self, text: str) -> bool:
        if not self.is_open:
            return False
        try:
            n = self._sock.sendTextMessage(text)
        except Exception as exc:                 # noqa: BLE001
            self.failed.emit(str(exc))
            return False
        data = text.encode("utf-8")
        self.bytes_out += len(data)
        self.frames_out += 1
        self._emit(WsFrame("out", frame_kind(data, False), data, size=len(data)))
        return n >= 0

    def send_binary(self, data: bytes) -> bool:
        if not self.is_open:
            return False
        try:
            self._sock.sendBinaryMessage(QByteArray(data))
        except Exception as exc:                 # noqa: BLE001
            self.failed.emit(str(exc))
            return False
        self.bytes_out += len(data)
        self.frames_out += 1
        self._emit(WsFrame("out", "binary", data, size=len(data)))
        return True

    def _on_text(self, text: str) -> None:
        data = (text or "").encode("utf-8")
        self.bytes_in += len(data)
        self.frames_in += 1
        self._emit(WsFrame("in", frame_kind(data, False), data, size=len(data)))

    def _on_binary(self, data) -> None:
        raw = bytes(data)
        self.bytes_in += len(raw)
        self.frames_in += 1
        self._emit(WsFrame("in", "binary", raw, size=len(raw)))

    def _emit(self, frame: WsFrame) -> None:
        if not frame.size:
            frame.size = len(frame.data)
        self.frame.emit(frame)

    # -------------------------------------------------- 心跳
    def _ping(self) -> None:
        if not self.is_open:
            return
        try:
            self._sock.ping(b"ocelot")
        except Exception:                        # noqa: BLE001
            return
        self._emit(WsFrame("out", "ping", b"ocelot", size=6))

    def _on_pong(self, elapsed: int, _payload) -> None:
        self.latency = int(elapsed)
        self.ponged.emit(self.latency)
        self._emit(WsFrame("in", "pong", f"{int(elapsed)} ms".encode("utf-8")))

    # -------------------------------------------------- 断开
    def disconnect_ws(self, code: int = 1000, reason: str = "客户端主动断开") -> None:
        self._manual = True
        self._retry_timer.stop()
        self._ping_timer.stop()
        if self._sock is None:
            self._set_state(STATE_CLOSED)
            return
        self._set_state(STATE_CLOSING)
        try:
            self._sock.close(code, reason)
        except Exception:                        # noqa: BLE001
            try:
                self._sock.abort()
            except Exception:                    # noqa: BLE001
                pass

    def abort(self) -> None:
        self._manual = True
        self._retry_timer.stop()
        self._ping_timer.stop()
        try:
            if self._sock is not None:
                self._sock.abort()
        except Exception:                        # noqa: BLE001
            pass
        self._set_state(STATE_CLOSED)

    def stats(self) -> Dict[str, Any]:
        uptime = time.time() - self.opened_at if self.opened_at and self.is_open else 0
        return {"state": self._state, "in": self.frames_in, "out": self.frames_out,
                "bytes_in": self.bytes_in, "bytes_out": self.bytes_out,
                "latency": self.latency, "uptime": uptime}
