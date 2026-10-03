"""Start de agent op de TEST-CLIENT:  python -m rpitest.agent"""

from __future__ import annotations

import argparse
import sys

from .. import config
from ..gpio import real
from ..sysinfo import pi_info
from ..system.linux import LinuxOps
from .core import Agent
from .server import make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest.agent", description="Agent op de TEST-CLIENT")
    parser.add_argument("--host", default=config.CLIENT_IP, help="IP-adres om op te luisteren (enkel de testkabel!)")
    parser.add_argument("--port", type=int, default=config.AGENT_PORT)
    parser.add_argument("--gpio-chip", help="pad van de gpiochip, bv. /dev/gpiochip0 (standaard: automatisch)")
    parser.add_argument("--list-chips", action="store_true", help="toon de gevonden gpiochips en stop")
    args = parser.parse_args(argv)

    try:
        if args.list_chips:
            for path, label, num_lines in real.list_chips():
                print(f"{path}  label={label}  lijnen={num_lines}")
            return 0
        port = real.GpiodPort(args.gpio_chip)
    except RuntimeError as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 2

    ops = LinuxOps()
    server = make_server(Agent(port, pi_info, ops), args.host, args.port)
    print(f"Agent luistert op {args.host}:{args.port} (GPIO-chip {port.chip_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        ops.close()
        port.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
