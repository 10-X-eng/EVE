"""Local HTTP servers that never perform reverse DNS during startup."""
from http.server import HTTPServer
from socketserver import TCPServer, ThreadingMixIn


class LoopbackHTTPServer(HTTPServer):
    def server_bind(self):
        if self.server_address[0] != "127.0.0.1":
            raise ValueError("STEVE's local HTTP servers must bind to IPv4 loopback.")
        # HTTPServer.server_bind calls getfqdn(), which can hang in macOS DNS.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


class ThreadingLoopbackHTTPServer(ThreadingMixIn, LoopbackHTTPServer):
    daemon_threads = True
