"""Hulpmiddelen voor de USB-fixture.

    python -m rpitest.usbtools scan
    python -m rpitest.usbtools prepare /dev/sdX --label SLOT1 [--yes]

`prepare` overschrijft sector 0 van de stick (partitietabel!) met onze header. Alleen voor
sticks die uitsluitend als teststick dienen."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path

from .system import parsers, storage
from .system.linux import LinuxOps

MAX_STICK_BYTES = 256 * 1024 ** 3  # grotere schijven zijn zeker geen teststick


def validate_prepare_target(device: str, label: str, root: Path = Path("/"),
                            realpath: Callable[[str], str] = os.path.realpath,
                            mounts: str | None = None) -> str | None:
    """Geeft een reden terug waarom `device` niet voorbereid mag worden, of None als het mag."""
    if not re.fullmatch(r"/dev/sd[a-z]{1,2}", device):
        return "alleen hele schijven zoals /dev/sdb zijn toegestaan (geen partities)"
    try:
        storage.make_header(label)
    except ValueError as exc:
        return str(exc)
    name = device.removeprefix("/dev/")
    if parsers.usb_path_from_syspath(realpath(str(root / "sys/block" / name))) is None:
        return f"{device} is geen USB-apparaat"
    try:
        size = int((root / "sys/block" / name / "size").read_text()) * 512
    except (OSError, ValueError):
        return f"grootte van {device} niet te bepalen"
    if size == 0 or size > MAX_STICK_BYTES:
        return f"{device} is {size / 1024 ** 3:.0f} GiB: lijkt geen teststick"
    if mounts is None:
        try:
            mounts = Path("/proc/mounts").read_text()
        except OSError:
            mounts = ""
    if any(line.split()[0].startswith(device) for line in mounts.splitlines() if line.strip()):
        return f"{device} is gekoppeld (mounted); ontkoppel hem eerst"
    return None


def _describe(device: str, root: Path = Path("/")) -> str:
    base = root / "sys/block" / device.removeprefix("/dev/")

    def read(rel: str) -> str:
        try:
            return (base / rel).read_text().strip()
        except OSError:
            return "?"

    size_gib = int(read("size")) * 512 / 1024 ** 3 if read("size").isdigit() else 0
    return f"{read('device/vendor')} {read('device/model')}, {size_gib:.1f} GiB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest.usbtools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="toon de aangesloten USB-apparaten en hun fixture-label")
    prep = sub.add_parser("prepare", help="geef een stick een fixture-label (wist sector 0!)")
    prep.add_argument("device", help="bv. /dev/sdb")
    prep.add_argument("--label", required=True, help="bv. SLOT1")
    prep.add_argument("--yes", action="store_true", help="bevestig dat sector 0 overschreven mag worden")
    args = parser.parse_args(argv)

    if args.command == "scan":
        for d in LinuxOps().usb_scan():
            print(f"{d['path']:10} {d['speed_mbit'] or '?':>7} Mb/s  {d['manufacturer'] or ''} {d['product'] or ''}"
                  f"  blok={d['block'] or '-'}  label={d['fixture_label'] or '-'}"
                  f"{'  (hub)' if d['is_hub'] else ''}")
        return 0

    reason = validate_prepare_target(args.device, args.label)
    if reason:
        print(f"Geweigerd: {reason}", file=sys.stderr)
        return 2
    print(f"{args.device}: {_describe(args.device)}")
    if not args.yes:
        print("Sector 0 (inclusief partitietabel) wordt overschreven. Voeg --yes toe om door te gaan.")
        return 1
    storage.write_label(args.device, args.label)
    found = storage.read_label(args.device)
    print(f"Label {found!r} geschreven." if found == args.label else "Controle na schrijven mislukt!")
    return 0 if found == args.label else 1


if __name__ == "__main__":
    sys.exit(main())
