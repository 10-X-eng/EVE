"""Inert MCP inventory inside Fusion; only STEVE dispatches executable tools."""
from http.server import BaseHTTPRequestHandler
import json
import secrets
import threading

from ..loopback_http import ThreadingLoopbackHTTPServer


class Inventory:
    def __init__(self, tools):
        route = "/" + secrets.token_urlsafe(32)

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != route or self.headers.get("Origin"):
                    self.send_error(404)
                    return
                self.connection.settimeout(15)
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if not 0 < size <= 1024 * 1024:
                        self.send_error(413)
                        return
                    row = json.loads(self.rfile.read(size))
                    method = row.get("method")
                    if "id" not in row:
                        self.send_response(202)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    if method == "initialize":
                        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "steve-inert-inventory", "version": "1"}}
                    elif method == "tools/list":
                        result = {"tools": tools}
                    elif method == "tools/call":
                        result = {"isError": True, "content": [{"type": "text", "text": "Only STEVE executes Fusion tools."}]}
                    else:
                        result = {}
                    data = json.dumps({"jsonrpc": "2.0", "id": row["id"], "result": result}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (OSError, ValueError):
                    self.close_connection = True

            def log_message(self, *args):
                pass

        self.server = ThreadingLoopbackHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}{route}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
