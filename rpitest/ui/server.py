"""HTTP-laag van het scherm (enkel stdlib). Luistert standaard alleen op 127.0.0.1: de kiosk-browser
draait op dezelfde Pi, en de start-/afsluitknoppen mogen niet vanaf een netwerk bereikbaar zijn
(de TEST-SERVER opent tijdens de wifi-test zelf een hotspot)."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..agent.client import RpcError
from ..report import REPORT_NAME
from .controller import Controller

STATIC = Path(__file__).parent / "static"
DEFAULT_PORT = 8080
MAX_BODY = 64 * 1024  # de pagina stuurt enkele bytes; alles groter is verdacht
MAX_DRAIN = 8 * 1024 * 1024  # zoveel van een te grote body lezen we nog leeg voor we weigeren
UI_UNIT = "rpitest-ui.service"
KIOSK_PROFILE = "--user-data-dir=/tmp/rpitest-kiosk"  # herkent de kioskbrowser (zie image/kiosk.sh)
SHUTDOWN_MODES = ("app", "poweroff")


def exit_flag_path(reports_dir: Path) -> Path:
    """Bestand dat image/kiosk.sh vertelt dat de browser bewust gesloten is en niet herstart moet worden."""
    return Path(reports_dir).parent / "kiosk-exit"


def _make_handler(controller: Controller, reports_dir: Path, allow_shutdown: bool, port_getter,
                  client_power_off: Callable[[], None] | None = None):
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
            # een cross-site formulier of fetch kan geen application/json zonder preflight sturen, en een pagina van
            # elders stuurt zijn eigen Origin mee: weiger beide, want hier starten we tests en schakelen we de Pi uit
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._json({"ok": False, "message": "alleen application/json"}, 415)
                return
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{self.headers.get('Host', '')}":
                self._send(403, b"verboden", "text/plain")
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = None
            if not isinstance(body, dict):  # een lijst, null of getal is geen aanvraag van de pagina
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
            """mode 'app': sluit de kioskbrowser en stop de dienst; mode 'poweroff': schakel de TEST-SERVER uit.
            Met client=true schakelt de TEST-SERVER eerst de TEST-CLIENT uit; lukt dat niet, dan gebeurt er niets."""
            mode, with_client = body.get("mode", "poweroff"), body.get("client", False)
            if not allow_shutdown:
                self._json({"ok": False, "message": "afsluiten is hier uitgeschakeld"}, 403)
            elif body.get("confirm") is not True:
                self._json({"ok": False, "message": "bevestiging ontbreekt"}, 400)
            elif mode not in SHUTDOWN_MODES or not isinstance(with_client, bool):
                self._json({"ok": False, "message": "ongeldige aanvraag"}, 400)
            elif controller.state()["phase"] == "running":
                self._json({"ok": False, "message": "er loopt een test"}, 409)
            elif with_client and client_power_off is None:
                self._json({"ok": False, "message": "de TEST-CLIENT uitschakelen kan hier niet"}, 400)
            else:
                if with_client:
                    try:
                        client_power_off()
                    except RpcError as exc:
                        self._json({"ok": False, "message": f"de TEST-CLIENT is niet uitgeschakeld ({exc}); "
                                                            "er is niets afgesloten"}, 502)
                        return
                suffix = " en de TEST-CLIENT wordt ook uitgeschakeld" if with_client else ""
                if mode == "poweroff":
                    self._json({"ok": True, "message": f"de TEST-SERVER wordt uitgeschakeld{suffix}"})
                    self._run_after_response([["systemctl", "poweroff"]])
                else:
                    flag = exit_flag_path(reports_dir)
                    try:
                        flag.write_text("1", encoding="utf-8")  # eerst het vlag, anders herstart kiosk.sh de browser
                    except OSError as exc:
                        self._json({"ok": False, "message": f"kan de applicatie niet afsluiten: {exc}"}, 500)
                        return
                    self._json({"ok": True, "message": f"de applicatie wordt gesloten{suffix}"})
                    self._run_after_response([["pkill", "-f", "--", KIOSK_PROFILE],
                                              ["systemctl", "--no-block", "stop", UI_UNIT]])

        def _run_after_response(self, commands: list[list[str]]) -> None:
            self.wfile.flush()
            for argv in commands:
                try:
                    subprocess.Popen(argv)
                except OSError:
                    pass  # bv. geen systemctl bij een ontwikkelrun; het antwoord is al verstuurd

    return Handler


def make_server(controller: Controller, reports_dir: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                allow_shutdown: bool = False, client_power_off: Callable[[], None] | None = None) -> ThreadingHTTPServer:
    holder: dict = {}
    handler = _make_handler(controller, reports_dir, allow_shutdown, lambda: holder["server"].server_address[1],
                            client_power_off)
    server = ThreadingHTTPServer((host, port), handler)
    holder["server"] = server
    return server
