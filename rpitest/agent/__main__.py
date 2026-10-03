"""Start de agent op de TEST-CLIENT:  python -m rpitest.agent"""

from __future__ import annotations

import argparse
import errno
import sys
import time

from .. import config
from ..gpio import real
from ..sysinfo import pi_info
from ..system.linux import LinuxOps
from .core import Agent
from .server import make_server


def bind_when_available(make, host: str, port: int, sleep=time.sleep, log=print):
    """Maak de server aan, en wacht zolang het adres nog niet bestaat.

    NetworkManager zet het vaste testadres pas bij link (kabel aangesloten). Zonder te wachten crasht de
    agent elke 2 s (systemd herstart hem), en lijkt de dienst 'niet te draaien'. Andere fouten (bv. poort
    bezet) worden niet herhaald."""
    announced = False
    while True:
        try:
            return make(host, port)
        except OSError as exc:
            if exc.errno != errno.EADDRNOTAVAIL:
                raise
            if not announced:
                log(f"Wachten tot het adres {host} bestaat (testkabel aangesloten?)...")
                announced = True
            sleep(2)


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
    agent = Agent(port, pi_info, ops)
    try:
        server = bind_when_available(lambda host, p: make_server(agent, host, p), args.host, args.port)
    except OSError as exc:
        print(f"Fout: kan niet luisteren op {args.host}:{args.port}: {exc}", file=sys.stderr)
        ops.close()
        port.close()
        return 2
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
