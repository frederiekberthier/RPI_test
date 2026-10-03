"""Minimale JSON-RPC over HTTP (enkel stdlib). Alleen bedoeld voor de directe kabel
tussen TEST-SERVER en TEST-CLIENT: er is geen authenticatie, bind dus nooit op een openbaar netwerk."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import Agent

DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024  # een aanroep is enkele bytes; alles groter is een fout
MAX_DRAIN = 1024 * 1024  # zoveel van een te grote body lezen we nog leeg voor we weigeren
DRAIN_TIMEOUT = 2.0  # en niet langer dan dit wachten we op een body die nooit komt


class _Handler(BaseHTTPRequestHandler):
    agent: Agent

    def _read_body(self) -> tuple[bytes | None, str]:
        """(body, foutmelding). Een ongeldige of te grote Content-Length wordt geweigerd; van een te grote body lezen
        we een beperkt stuk leeg (anders breekt de verbinding af voordat de client het antwoord ziet)."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, "ongeldige Content-Length"
        if length < 0:
            return None, "ongeldige Content-Length"
        if length > MAX_BODY:
            self.connection.settimeout(DRAIN_TIMEOUT)
            remaining = min(length, MAX_DRAIN)
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass
            self.close_connection = True
            return None, f"aanvraag te groot (maximaal {MAX_BODY} bytes)"
        return self.rfile.read(length), ""

    def do_POST(self) -> None:
        if self.path != "/rpc":
            self.send_error(404)
            return
        status = 200
        raw, problem = self._read_body()
        if raw is None:
            status = 413 if "te groot" in problem else 400
            body = {"error": problem}
        else:
            try:
                request = json.loads(raw)
                body = {"result": self.agent.dispatch(request["method"], request.get("params", {}))}
            except Exception as exc:  # fouten gaan terug naar de TEST-SERVER, niet in de agent-log
                body = {"error": f"{type(exc).__name__}: {exc}"}
        payload = json.dumps(body).encode()
        self.send_response(status)
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
