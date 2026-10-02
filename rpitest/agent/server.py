"""Minimale JSON-RPC over HTTP (enkel stdlib). Alleen bedoeld voor de directe kabel
tussen testpi en DUT: er is geen authenticatie, bind dus nooit op een openbaar netwerk."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import Agent

DEFAULT_PORT = 8765


class _Handler(BaseHTTPRequestHandler):
    agent: Agent

    def do_POST(self) -> None:
        if self.path != "/rpc":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length))
            body = {"result": self.agent.dispatch(request["method"], request.get("params", {}))}
        except Exception as exc:  # fouten gaan terug naar de tester, niet in de agent-log
            body = {"error": f"{type(exc).__name__}: {exc}"}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


def make_server(agent: Agent, host: str, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"agent": agent})
    return ThreadingHTTPServer((host, port), handler)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread
