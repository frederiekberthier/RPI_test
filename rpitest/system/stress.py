"""Belastingsworkers voor de voedings- en temperatuurtest.

Elke worker is een eigen proces (`python -m rpitest.system.stress cpu|ram ...`) en schrijft aan het
einde één regel JSON. Het werk is deterministisch, zodat een afwijking op een foutieve CPU of
geheugencel wijst."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time

CPU_SEED = b"rpitest"
CPU_ROUND_ITERATIONS = 200_000
# sha256-keten van CPU_ROUND_ITERATIONS stappen vanaf CPU_SEED
CPU_EXPECTED = bytes.fromhex("af0d691e456d02e54894b827f4b6ac05abddb02fc5249486a5087bf7f7811675")
CHUNK = 1 << 20


def cpu_round(iterations: int = CPU_ROUND_ITERATIONS) -> bytes:
    h = CPU_SEED
    for _ in range(iterations):
        h = hashlib.sha256(h).digest()
    return h


def cpu_worker(seconds: float, round_fn=cpu_round, expected: bytes = CPU_EXPECTED) -> dict:
    deadline = time.monotonic() + seconds
    rounds = bad = 0
    while True:  # minstens één ronde, ook bij een heel korte looptijd
        if round_fn() != expected:
            bad += 1
        rounds += 1
        if time.monotonic() >= deadline:
            break
    return {"role": "cpu", "rounds": rounds, "bad": bad}


def _patterns():
    """Vaste patronen plus een adresafhankelijk patroon dat per blok verschuift."""
    for byte in (0x55, 0xAA, 0x00, 0xFF):
        yield f"{byte:#04x}", lambda i, b=byte: bytes([b]) * CHUNK
    base = bytes(range(256)) * (CHUNK // 256)
    yield "adres", lambda i: base[i % 256:] + base[:i % 256]


def ram_pass(buf: bytearray) -> int:
    """Eén volledige ronde over alle patronen. Geeft het aantal foute blokken terug."""
    bad = 0
    n_chunks = len(buf) // CHUNK
    for _, make in _patterns():
        for i in range(n_chunks):
            buf[i * CHUNK:(i + 1) * CHUNK] = make(i)
        for i in range(n_chunks):
            if buf[i * CHUNK:(i + 1) * CHUNK] != make(i):
                bad += 1
    return bad


def ram_worker(seconds: float, mb: int) -> dict:
    buf = bytearray(mb * CHUNK)
    deadline = time.monotonic() + seconds
    passes = bad = 0
    while True:
        bad += ram_pass(buf)
        passes += 1
        if time.monotonic() >= deadline:
            break
    return {"role": "ram", "passes": passes, "bad": bad, "mb": mb}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpitest.system.stress")
    parser.add_argument("role", choices=("cpu", "ram"))
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--mb", type=int, default=64)
    args = parser.parse_args(argv)
    result = cpu_worker(args.seconds) if args.role == "cpu" else ram_worker(args.seconds, args.mb)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
