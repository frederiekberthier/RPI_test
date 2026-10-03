from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import factory
from . import report as report_mod
from .runner import run_all


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mock", action="store_true", help="gesimuleerde testpi + DUT (geen hardware nodig)")
    parser.add_argument("--fault", action="append", default=[], metavar="SPEC",
                        help="fout injecteren in de mock, bv. stuck_low:D:5, bridge:D:5:6, open:7, eth_100, "
                             "no_wifi, no_bt, usb_slot3_dead, power_hot")
    parser.add_argument("--dut-url", default=factory.default_dut_url(),
                        help="adres van de agent op de DUT (echte hardware)")
    parser.add_argument("--gpio-chip", help="pad van de gpiochip van de testpi (standaard: automatisch)")
    parser.add_argument("--usb-fixture", type=Path, metavar="BESTAND",
                        help="JSON-lijst met USB-slots i.p.v. config.USB_SLOTS")
    parser.add_argument("--out", "--reports", dest="out", type=Path, default=Path("reports"),
                        help="map voor de rapporten")


def context_factory(args) -> factory.ContextFactory:
    """Een functie die bij elke run een verse Context (en een opruimfunctie) maakt."""
    slots = factory.load_usb_slots(args.usb_fixture)
    if args.mock:
        return lambda: factory.mock_context(args.fault, slots)
    return lambda: factory.real_context(args.dut_url, args.gpio_chip, slots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest", description="Test een tweedehands Raspberry Pi")
    add_common_arguments(parser)
    args = parser.parse_args(argv)

    try:
        make_context = context_factory(args)
    except (OSError, ValueError) as exc:
        print(f"Fout: USB-fixturebestand niet te lezen: {exc}", file=sys.stderr)
        return 2
    try:
        ctx, close = make_context()
    except RuntimeError as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 2

    try:
        report = run_all(ctx)
    finally:
        close()
    for r in report.results:
        print(f"[{r.status.value:4}] {r.name}: {r.summary}")
    json_path, html_path = report_mod.save(report, args.out)
    print(f"\nEindoordeel: {report.overall}\nRapport: {html_path}\n         {json_path}")
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
