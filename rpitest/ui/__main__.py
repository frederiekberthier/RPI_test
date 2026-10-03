"""Start het scherm van de TEST-SERVER:  python -m rpitest.ui

Op de TEST-SERVER draait dit als systemd-dienst; Chromium toont de pagina in kioskmodus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import factory
from ..__main__ import add_common_arguments, context_factory
from .controller import Controller
from .server import DEFAULT_PORT, make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest.ui", description="Scherm en startknop van de TEST-SERVER")
    add_common_arguments(parser)
    parser.add_argument("--host", default="127.0.0.1", help="enkel lokaal laten staan (standaard)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--allow-shutdown", action="store_true", help="toon een knop om de TEST-SERVER uit te schakelen")
    args = parser.parse_args(argv)

    try:
        make_context = context_factory(args)
    except (OSError, ValueError) as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 2
    probe = factory.mock_probe if args.mock else factory.real_probe(args.client_url)

    reports = Path(args.out)
    controller = Controller(make_context, probe, reports)
    controller.refresh_client()
    controller.start_polling()
    server = make_server(controller, reports, args.host, args.port, args.allow_shutdown)
    print(f"Scherm beschikbaar op http://{args.host}:{args.port}  (rapporten in {reports})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
