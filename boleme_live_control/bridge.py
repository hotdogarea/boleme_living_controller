"""Loopback-only event stream and text-reply command endpoint."""

import hmac
import json
import queue
import threading

from PyQt6.QtCore import QObject, pyqtSignal


class Bridge(QObject):
    send_requested = pyqtSignal(dict)
    status_changed = pyqtSignal(str)

    def __init__(self, token: str, port: int = 21341, parent=None):
        super().__init__(parent)
        self.token = token
        self.port = port
        self._stop = threading.Event()
        self._clients = set()
        self._lock = threading.Lock()
        self._thread = None
        self._platform_status = "未连接平台"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        from websockets.sync.server import serve
        self._server = serve(self._handle, "127.0.0.1", self.port)
        self._thread = threading.Thread(target=self._run, daemon=True, name="boleme-bridge")
        self._thread.start()

    def _run(self):
        try:
            with self._server as server:
                self.status_changed.emit(f"本机通信已就绪: 127.0.0.1:{self.port}")
                server.serve_forever()
        except Exception as exc:
            self.status_changed.emit(f"本机通信启动失败: {exc}")

    def _handle(self, socket):
        pending = queue.Queue(maxsize=500)
        try:
            hello = json.loads(socket.recv(timeout=5))
            if not hmac.compare_digest(str(hello.get("token", "")), self.token):
                socket.close(code=1008, reason="unauthorized")
                return
            with self._lock:
                self._clients.add(pending)
            socket.send(json.dumps({"type": "ready", "version": 1}, ensure_ascii=False))
            socket.send(json.dumps({"type": "platform_status", "status": self._platform_status}, ensure_ascii=False))
            while not self._stop.is_set():
                try:
                    while True:
                        socket.send(pending.get_nowait())
                except queue.Empty:
                    pass
                try:
                    raw = socket.recv(timeout=0.1)
                except TimeoutError:
                    continue
                command = json.loads(raw)
                if command.get("type") == "send_text":
                    value = command.get("text")
                    msg_id = command.get("msg_id", "")
                    if (isinstance(value, str) and 0 < len(value.strip()) <= 300
                            and isinstance(msg_id, str) and len(msg_id) <= 200
                            and isinstance(command.get("session_id"), str)
                            and isinstance(command.get("platform"), str)):
                        self.send_requested.emit(command)
                    else:
                        socket.send(json.dumps({"type": "error", "message": "invalid text"}))
        except Exception:
            pass
        finally:
            with self._lock:
                self._clients.discard(pending)

    def broadcast(self, event: dict):
        payload = json.dumps({"type": "barrage", "event": event}, ensure_ascii=False)
        self._broadcast_payload(payload)

    def broadcast_status(self, status: str):
        self._platform_status = status
        self._broadcast_payload(json.dumps({"type": "platform_status", "status": status}, ensure_ascii=False))

    def _broadcast_payload(self, payload: str):
        with self._lock:
            for client in self._clients:
                try:
                    client.put_nowait(payload)
                except queue.Full:
                    try:
                        client.get_nowait()
                        client.put_nowait(payload)
                    except queue.Empty:
                        pass

    def stop(self):
        self._stop.set()
        server = getattr(self, "_server", None)
        if server:
            server.shutdown()
        if self._thread:
            self._thread.join(timeout=2)
