from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report as report_mod
from .agent.client import LocalClient, RemoteGpioPort
from .agent.core import Agent
from .context import Context
from .gpio.mock import DUT, TESTER, MockWiring
from .runner import run_all


def _mock_context(faults: list[str]) -> Context:
    wiring = MockWiring()
    for spec in faults:  # bv. stuck_low:D:5  stuck_high:T:9  bridge:D:5:6  open:7
        kind, *args = spec.split(":")
        wiring.add_fault(kind, *args)
    info = {"model": "Raspberry Pi 5 Model B Rev 1.0 (mock)", "ram_mb": 8192, "serial": "MOCK0001"}
    client = LocalClient(Agent(wiring.port(DUT), lambda: info))
    tester_info = {"model": "Raspberry Pi 5 (mock tester)"}
    return Context(wiring.port(TESTER), RemoteGpioPort(client), client, tester_info)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest", description="Test een tweedehands Raspberry Pi")
    parser.add_argument("--mock", action="store_true", help="gesimuleerde testpi + DUT (geen hardware nodig)")
    parser.add_argument("--fault", action="append", default=[], metavar="SPEC",
                        help="fout injecteren in de mock, bv. stuck_low:D:5, bridge:D:5:6, open:7")
    parser.add_argument("--out", type=Path, default=Path("reports"), help="map voor de rapporten")
    args = parser.parse_args(argv)

    if not args.mock:
        print("De echte hardware-backend is nog niet geimplementeerd; gebruik --mock.", file=sys.stderr)
        return 2

    report = run_all(_mock_context(args.fault))
    for r in report.results:
        print(f"[{r.status.value:4}] {r.name}: {r.summary}")
    json_path, html_path = report_mod.save(report, args.out)
    print(f"\nEindoordeel: {report.overall}\nRapport: {html_path}\n         {json_path}")
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
