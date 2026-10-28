"""mcp-for-blender 的最小客户端：直连 Blender 插件的 TCP socket。

不依赖 MCP 框架，任何 Python 都能用；也可以被任意 LLM 驱动端调用。

协议（来自 addon 源码）：JSON over TCP，命令 {"type": ..., "params": {...}}，
响应 {"status": "success"|"error", "result"/"message": ...}。
"""

import json
import socket
import time

HOST = "127.0.0.1"
PORT = 9876


class BlenderMCP:
    def __init__(self, host=HOST, port=PORT, timeout=120):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None

    # ---------- 连接管理 ----------
    def connect(self, retries=30, delay=1.0):
        """等待 Blender 插件的 socket 服务就绪。"""
        last = None
        for _ in range(retries):
            try:
                s = socket.create_connection((self.host, self.port), timeout=5)
                s.settimeout(self.timeout)
                self._sock = s
                return True
            except Exception as e:                        # noqa: BLE001
                last = e
                time.sleep(delay)
        raise ConnectionError(f"无法连接 {self.host}:{self.port} ({last})")

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    # ---------- 底层收发 ----------
    def _send(self, payload: dict) -> dict:
        if self._sock is None:
            self.connect()
        data = json.dumps(payload).encode("utf-8")
        self._sock.sendall(data)
        # 插件用 client.sendall(response_json) 回包：**无分隔符、无长度前缀**。
        # 所以必须自己累积缓冲，反复尝试整块 JSON 解析（可能分片到达）。
        buf = b""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            text = buf.decode("utf-8", errors="ignore")
            # 1) 整块就是完整 JSON（最常见）
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
            # 2) 退路：按行切
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise TimeoutError(
            f"等待响应超时/无法解析，已收 {len(buf)} 字节: {buf[:400]!r}")

    @staticmethod
    def _split_json(buf: bytes):
        """按行/整块尝试切出候选 JSON 片段。"""
        text = buf.decode("utf-8", errors="ignore")
        for piece in text.split("\n"):
            piece = piece.strip()
            if piece:
                yield piece
        if text.strip():
            yield text.strip()

    # ---------- 高层命令 ----------
    def execute_code(self, code: str):
        """在活着的 Blender 里执行 Python。返回 dict。"""
        return self._send({"type": "execute_code", "params": {"code": code}})

    def get_scene_info(self):
        return self._send({"type": "get_scene_info", "params": {}})

    def get_viewport_screenshot(self, filepath: str, view: str = "camera",
                               max_size: int = 1400, overlay: bool = False):
        return self._send({"type": "get_viewport_screenshot", "params": {
            "filepath": filepath, "view": view,
            "max_size": max_size, "overlay": overlay}})

    def get_addon_status(self):
        return self._send({"type": "get_addon_status", "params": {}})


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python blender_client.py <要执行的 Blender Python 代码文件>")
        print("或:   python blender_client.py --status")
        sys.exit(1)

    if sys.argv[1] == "--status":
        c = BlenderMCP()
        c.connect()
        print("connected")
        print("addon_status:", json.dumps(c.get_addon_status(), ensure_ascii=False)[:800])
        c.close()
    else:
        code = open(sys.argv[1], encoding="utf-8").read()
        c = BlenderMCP()
        c.connect()
        r = c.execute_code(code)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:4000])
        c.close()
