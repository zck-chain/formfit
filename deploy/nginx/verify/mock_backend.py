"""本地验证用最小后端（仅 deploy/nginx/docker-compose.verify.yml 使用，勿用于生产）。

它模拟 FormFit FastAPI 的几个关键路由，目的是验证 Nginx 同源反代/静态路由是否正确：
  - GET  /healthz            -> 200 {"status":"ok"}
  - any  /api/...            -> 200 JSON 回显 method/path（证明被反代，而非 SPA HTML）
  - POST /api/fitness/assess -> 200 JSON 回显收到的字节数（证明上传体透传）
  - GET  /media/...          -> 200 返回一张 1x1 PNG（证明素材可经反代访问）
  - GET  /static/...         -> 200 文本（证明 /static 反代）
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 1x1 透明 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
        elif self.path.startswith("/media/"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
        elif self.path.startswith("/static/"):
            body = b"static-ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/api/"):
            self._send_json(200, {"proxied": True, "method": "GET", "path": self.path})
        else:
            self._send_json(404, {"detail": "not found", "path": self.path})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        # 把请求体读完（模拟后端接收上传），但不落盘
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                break
            remaining -= len(chunk)
        if self.path.startswith("/api/"):
            self._send_json(
                200,
                {"proxied": True, "method": "POST", "path": self.path,
                 "received_bytes": length},
            )
        else:
            self._send_json(404, {"detail": "not found"})

    def log_message(self, fmt, *args):
        # 安静一点，只在出错时有意义
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
