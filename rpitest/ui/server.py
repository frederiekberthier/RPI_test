"""HTTP-laag van het scherm (enkel stdlib). Luistert standaard alleen op 127.0.0.1: de kiosk-browser
draait op dezelfde Pi, en de start-/afsluitknoppen mogen niet vanaf een netwerk bereikbaar zijn
(de TEST-SERVER opent tijdens de wifi-test zelf een hotspot)."""

from __future__ import annotations

import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..report import REPORT_NAME
from .controller import Controller

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8080
MAX_BODY = 64 * 1024  # de pagina stuurt enkele bytes; alles groter is verdacht
MAX_DRAIN = 8 * 1024 * 1024  # zoveel van een te grote body lezen we nog leeg voor we weigeren


def _make_handler(controller: Controller, reports_dir: Path, allow_shutdown: bool, port_getter):
    class Handler(BaseHTTPRequestHandler):
        server_version = "rpitest-ui"

        # ---- hulpfuncties
        def _host_ok(self) -> bool:
            port = port_getter()
            return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def log_message(self, *args) -> None:
            pass

        # ---- routes
        def do_GET(self) -> None:
            if not self._host_ok():
                self._send(403, b"verboden", "text/plain")
            elif self.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json({**controller.state(), "shutdown_allowed": allow_shutdown})
            elif self.path.startswith("/reports/"):
                self._report(self.path.removeprefix("/reports/"))
            else:
                self._send(404, b"niet gevonden", "text/plain")

        def _report(self, name: str) -> None:
            # alleen onze eigen bestandsnamen, geen paden: geen manier om buiten de map te lezen
            path = reports_dir / name
            if not REPORT_NAME.match(name) or not path.is_file():
                self._send(404, b"niet gevonden", "text/plain")
                return
            kind = "text/html; charset=utf-8" if name.endswith(".html") else "application/json"
            self._send(200, path.read_bytes(), kind)

        def _read_body(self) -> bytes | None:
            """Leest altijd de volledige body, ook als we de aanvraag daarna weigeren: antwoorden met een
            ongelezen body laat de verbinding afbreken voordat de client het antwoord ziet."""
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                return None
            if length < 0:
                return None
            if length > MAX_BODY:
                remaining = min(length, MAX_DRAIN)  # te groot: weggooien, maar wel uitlezen
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                return None
            return self.rfile.read(length)

        def do_POST(self) -> None:
            raw = self._read_body()
            if raw is None:
                self._json({"ok": False, "message": "ongeldige aanvraag"}, 400)
                return
            if not self._host_ok():
                self._send(403, b"verboden", "text/plain")
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._json({"ok": False, "message": "ongeldige aanvraag"}, 400)
                return
            actions = {"/api/start": controller.start, "/api/abort": controller.abort, "/api/reset": controller.reset}
            if self.path in actions:
                ok, message = actions[self.path]()
                self._json({"ok": ok, "message": message}, 200 if ok else 409)
            elif self.path == "/api/shutdown":
                self._shutdown(body)
            else:
                self._send(404, b"niet gevonden", "text/plain")

        def _shutdown(self, body: dict) -> None:
            if not allow_shutdown:
                self._json({"ok": False, "message": "afsluiten is hier uitgeschakeld"}, 403)
            elif body.get("confirm") is not True:
                self._json({"ok": False, "message": "bevestiging ontbreekt"}, 400)
            elif controller.state()["phase"] == "running":
                self._json({"ok": False, "message": "er loopt een test"}, 409)
            else:
                self._json({"ok": True, "message": "de TEST-SERVER wordt uitgeschakeld"})
                subprocess.Popen(["systemctl", "poweroff"])

    return Handler


def make_server(controller: Controller, reports_dir: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                allow_shutdown: bool = False) -> ThreadingHTTPServer:
    holder: dict = {}
    handler = _make_handler(controller, reports_dir, allow_shutdown, lambda: holder["server"].server_address[1])
    server = ThreadingHTTPServer((host, port), handler)
    holder["server"] = server
    return server
