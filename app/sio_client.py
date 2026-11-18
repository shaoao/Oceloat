"""Socket.IO 连接层（Engine.IO v4 / Socket.IO v4，基于 QWebSocket，纯事件驱动）。

只走 websocket transport，不引入 python-socketio / httpx 等依赖：
一个客户端一条连接，握手、命名空间、事件、ACK、心跳和重连都在本文件里完成，
日志复用 WsFrame，由上层同一套列表渲染。内存占用和 WebSocket 页面相当。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional, Tuple

from PyQt6.QtCore import QUrl, QUrlQuery, pyqtSignal

from . import i18n
from .ws_client import STATE_CLOSED, STATE_CONNECTING, STATE_OPEN, WsClient, WsFrame, ws_url

# Socket.IO 包类型
SIO_CONNECT = "0"
SIO_DISCONNECT = "1"
SIO_EVENT = "2"
SIO_ACK = "3"
SIO_CONNECT_ERROR = "4"
SIO_BINARY_EVENT = "5"
SIO_BINARY_ACK = "6"


def sio_url(raw: str) -> str:
    """把地址补成 Engine.IO websocket 握手地址，保留用户已有的查询参数。"""
    target = ws_url(raw)
    if not target:
        return ""
    u = QUrl(target)
    path = u.path() or "/"
    if path == "/":
        path = "/socket.io/"
    u.setPath(path)
    q = QUrlQuery(u.query())
    q.removeQueryItem("EIO")
    q.removeQueryItem("transport")
    q.addQueryItem("EIO", "4")
    q.addQueryItem("transport", "websocket")
    u.setQuery(q)
    return u.toString()


def normalize_ns(ns: str) -> str:
    text = (ns or "").strip()
    if not text or text == "/":
        return "/"
    return text if text.startswith("/") else "/" + text


def ns_prefix(ns: str) -> str:
    """默认命名空间不写前缀；自定义命名空间要用 `ns,` 开头。"""
    return "" if normalize_ns(ns) == "/" else normalize_ns(ns) + ","


def split_ns(body: str) -> Tuple[str, str]:
    """拆 `namespace,payload`；没有逗号或不是 `/` 开头就是默认命名空间。"""
    text = body or ""
    if text.startswith("/"):
        i = text.find(",")
        if i >= 0:
            return normalize_ns(text[:i]), text[i + 1:]
        return normalize_ns(text), ""
    return "/", text


def compact(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class SocketIoClient(WsClient):
    """一条 Socket.IO 连接；信号与 WsClient 完全一致，可直接复用主窗口的槽。"""

    eventReceived = pyqtSignal(str, str)   # 事件名, 参数 JSON 数组文本
    acked = pyqtSignal(int, str)           # ack id, 参数 JSON 数组文本

    def __init__(self, parent=None):
        super().__init__(parent)
        self._namespace = "/"
        self._auth_text = ""
        self._sio_connected = False
        self._sid = ""
        self._ack_id = 0
        self._ping_sent_at = 0.0
        self._acks: Dict[int, float] = {}   # 等待回执的 ack id -> 发出时间

    # -------------------------------------------------- 连接
    def connect_to(self, url: str, headers=None, protocol: str = "",
                   namespace: Optional[str] = None, auth: Optional[str] = None, *,
                   auto_reconnect: bool = False, ping_secs: int = 0,
                   verify_ssl: bool = True) -> bool:
        # 自动重连时基类不会传 namespace / auth，沿用上一次的值，避免认证丢失
        if namespace is not None:
            self._namespace = normalize_ns(namespace)
        if auth is not None:
            self._auth_text = str(auth)
        self._sio_connected = False
        self._sid = ""
        self._ack_id = 0
        self._ping_sent_at = 0.0
        target = sio_url(url)
        if not target:
            self.failed.emit(i18n.tr("请先填写 ws:// 或 wss:// 地址"))
            return False
        return super().connect_to(target, headers, protocol,
                                  auto_reconnect=auto_reconnect,
                                  ping_secs=ping_secs, verify_ssl=verify_ssl)

    def _on_connected(self) -> None:
        """WebSocket 通了还不算连上：要等服务端回 40 才算 Socket.IO 会话建立。"""
        self._claimed = True
        self._attempt = 0
        self.opened_at = time.time()
        self._emit(WsFrame("sys", "open",
                           i18n.trf("传输已建立 · 命名空间 {ns}", ns=self._namespace)
                           .encode("utf-8")))
        if self._ping_secs:
            self._ping_timer.start(self._ping_secs * 1000)

    def _send_connect(self) -> None:
        payload = ""
        if self._auth_text.strip():
            try:
                auth = json.loads(self._auth_text)
                if not isinstance(auth, dict):
                    raise ValueError("auth must be an object")
                payload = compact(auth)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(i18n.trf("认证 JSON 无效：{msg}", msg=str(exc)))
        packet = "40" + ns_prefix(self._namespace) + payload
        self._raw_send(packet, "open")

    # -------------------------------------------------- 收包
    def _on_text(self, text: str) -> None:
        raw = (text or "").encode("utf-8")
        if not raw:
            return
        self.bytes_in += len(raw)
        self.frames_in += 1
        body = text
        kind = body[:1]
        rest = body[1:]
        if kind == "0":
            self._on_engine_open(rest)
        elif kind == "1":
            self._on_engine_close()
        elif kind == "2":
            # 服务端心跳：必须回 3，否则会被踢下线
            self._raw_send("3", "pong")
            self._emit(WsFrame("in", "ping", b"", size=0))
        elif kind == "3":
            ms = 0
            if self._ping_sent_at:
                ms = int(max(0.0, (time.time() - self._ping_sent_at) * 1000))
                self._ping_sent_at = 0.0
            self.latency = ms
            if ms:
                self.ponged.emit(ms)
            self._emit(WsFrame("in", "pong", f"{ms} ms".encode("utf-8"), size=0))
        elif kind == "4":
            self._on_message(rest)
        else:
            self._emit(WsFrame("in", "text", raw, size=len(raw)))

    def _on_engine_open(self, rest: str) -> None:
        info: Dict[str, Any] = {}
        try:
            data = json.loads(rest)
            if isinstance(data, dict):
                info = data
        except Exception:  # noqa: BLE001
            pass
        self._sid = str(info.get("sid") or "")
        self._emit(WsFrame("sys", "open", compact(info).encode("utf-8")))
        self._send_connect()

    def _on_engine_close(self) -> None:
        self._sio_connected = False
        self._emit(WsFrame("sys", "close", i18n.tr("服务端已关闭传输").encode("utf-8")))

    def _on_message(self, rest: str) -> None:
        if not rest:
            return
        kind = rest[:1]
        body = rest[1:]
        if kind == SIO_CONNECT:
            ns, payload = split_ns(body)
            sid = ""
            if payload:
                try:
                    data = json.loads(payload)
                    if isinstance(data, dict):
                        sid = str(data.get("sid") or "")
                except Exception:  # noqa: BLE001
                    pass
            self._sid = sid or self._sid
            self._sio_connected = True
            self._set_state(STATE_OPEN)
            self.opened.emit(self._sid or self._namespace)
            self._emit(WsFrame("sys", "open",
                               i18n.trf("已加入命名空间 {ns}", ns=ns).encode("utf-8")))
        elif kind == SIO_DISCONNECT:
            ns, _payload = split_ns(body)
            self._sio_connected = False
            self._emit(WsFrame("sys", "close",
                               i18n.trf("服务端断开命名空间 {ns}", ns=ns).encode("utf-8")))
            self._set_state(STATE_CLOSED)
            self.closed.emit(1000, i18n.tr("服务端主动断开"))
        elif kind == SIO_EVENT:
            self._on_event(body)
        elif kind == SIO_ACK:
            self._on_ack(body)
        elif kind == SIO_CONNECT_ERROR:
            ns, payload = split_ns(body)
            msg = payload or i18n.tr("连接被服务端拒绝")
            try:
                data = json.loads(payload)
                if isinstance(data, dict):
                    msg = str(data.get("message") or compact(data))
            except Exception:  # noqa: BLE001
                pass
            self.failed.emit(msg)
            self._emit(WsFrame("sys", "error", msg.encode("utf-8")))
        elif kind in (SIO_BINARY_EVENT, SIO_BINARY_ACK):
            raw = body.encode("utf-8")
            self._emit(WsFrame("in", "binary", raw, size=len(raw)))
            self.failed.emit(i18n.tr("暂不支持二进制附件事件，请发送 JSON 或文本事件"))

    def _on_event(self, body: str) -> None:
        ns, payload = split_ns(body)
        try:
            arr = json.loads(payload) if payload else []
        except Exception:  # noqa: BLE001
            arr = [payload]
        if not isinstance(arr, list) or not arr:
            raw = payload.encode("utf-8")
            self._emit(WsFrame("in", "text", raw, size=len(raw)))
            return
        event = str(arr[0])
        args = list(arr[1:])
        ack_id = None
        # 服务端要求回执时，ack id 紧跟事件名（arr[1]）；自动回一个空 ack。
        # 不能看最后一个参数——那可能只是普通的整数业务数据。
        if args and isinstance(args[0], int) and not isinstance(args[0], bool):
            ack_id = args.pop(0)
        frame_data = compact([event] + args).encode("utf-8")
        self._emit(WsFrame("in", "event", frame_data, size=len(frame_data)))
        self.eventReceived.emit(event, compact(args))
        if ack_id is not None:
            self._raw_send("43" + ns_prefix(ns) + str(ack_id) + "[]", "ack")

    def _on_ack(self, body: str) -> None:
        ns, payload = split_ns(body)
        m = re.match(r"^(\d+)(.*)$", payload or "")
        if not m:
            return
        ack_id = int(m.group(1))
        try:
            args = json.loads(m.group(2)) if m.group(2) else []
        except Exception:  # noqa: BLE001
            args = []
        self._acks.pop(ack_id, None)
        frame_data = compact({"id": ack_id, "args": args}).encode("utf-8")
        self._emit(WsFrame("in", "ack", frame_data, size=len(frame_data)))
        self.acked.emit(ack_id, compact(args))

    # -------------------------------------------------- 发送
    def _raw_send(self, packet: str, kind: str) -> bool:
        if self._sock is None:
            return False
        try:
            n = self._sock.sendTextMessage(packet)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return False
        data = packet.encode("utf-8")
        self.bytes_out += len(data)
        self.frames_out += 1
        self._emit(WsFrame("out", kind, data, size=len(data)))
        return n >= 0

    def emit_event(self, event: str, payload: str = "", with_ack: bool = False) -> bool:
        """发送一个 Socket.IO 事件；payload 能解析成 JSON 就按 JSON 发，否则按文本发。"""
        if not self.is_open or not self._sio_connected:
            return False
        name = (event or "").strip()
        if not name:
            self.failed.emit(i18n.tr("先输入事件名"))
            return False
        raw = (payload or "").strip()
        value: Any = ""
        if raw:
            try:
                value = json.loads(raw)
            except Exception:  # noqa: BLE001
                value = raw
        args: list = [name]
        if raw:
            args.append(value)
        ack_id = None
        if with_ack:
            self._ack_id += 1
            ack_id = self._ack_id
            self._acks[ack_id] = time.time()
            args.append(ack_id)
        packet = "42" + ns_prefix(self._namespace) + compact(args)
        ok = self._raw_send(packet, "event")
        if ok and ack_id is not None:
            self._emit(WsFrame("sys", "ack",
                               i18n.trf("等待 ACK · {id}", id=ack_id).encode("utf-8")))
        return ok

    def _ping(self) -> None:
        if self._sock is None:
            return
        self._ping_sent_at = time.time()
        self._raw_send("2", "ping")

    # -------------------------------------------------- 断开
    def disconnect_ws(self, code: int = 1000, reason: str = "客户端主动断开") -> None:
        if self._sio_connected and self._sock is not None:
            self._raw_send("41" + ns_prefix(self._namespace), "close")
        self._sio_connected = False
        super().disconnect_ws(code, reason)

    def abort(self) -> None:
        self._sio_connected = False
        super().abort()

    def stats(self) -> Dict[str, Any]:
        data = super().stats()
        data["namespace"] = self._namespace
        data["sid"] = self._sid
        return data
