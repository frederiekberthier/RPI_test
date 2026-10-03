"""Lees/schrijftest op de USB-teststicks.

Veiligheid: er wordt alleen geschreven naar een apparaat waarvan sector 0 onze header
(MAGIC + label) bevat, en uitsluitend in een testgebied ver voorbij het begin van de stick.
Een stick van een student die toevallig in de TEST-CLIENT zit, heeft die header niet en blijft onaangeroerd."""

from __future__ import annotations

import hashlib
import mmap
import os
import time

from .ops import OpsError

MAGIC = b"RPITEST-FIXTURE\0"
SECTOR = 512
CHUNK = 1 << 20  # 1 MiB; veelvoud van de sectorgrootte en pagina-uitgelijnd via mmap
MAX_LABEL = 32
SCRATCH_OFFSET_MB = 16


def make_header(label: str) -> bytes:
    raw = label.encode("ascii")
    if not 1 <= len(raw) <= MAX_LABEL or not label.isprintable():
        raise ValueError(f"label moet 1 tot {MAX_LABEL} afdrukbare ASCII-tekens zijn")
    return (MAGIC + raw).ljust(SECTOR, b"\0")


def _flags(direct: bool) -> int:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    return flags | getattr(os, "O_DIRECT", 0) if direct else flags


def read_label(path: str) -> str | None:
    """Het fixture-label van het apparaat, of None als de header ontbreekt of het niet leesbaar is."""
    try:
        with open(path, "rb", buffering=0) as f:
            head = f.read(SECTOR)
    except OSError:
        return None
    if not head.startswith(MAGIC):
        return None
    return head[len(MAGIC):].split(b"\0", 1)[0].decode("ascii", errors="replace") or None


def write_label(path: str, label: str) -> None:
    """Schrijft de header in sector 0. De aanroeper moet eerst gecontroleerd hebben dat het
    om een USB-stick gaat die gewist mag worden."""
    header = make_header(label)
    fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    try:
        os.write(fd, header)
        os.fsync(fd)
    finally:
        os.close(fd)


def run_storage_test(path: str, size_mb: int, offset_mb: int = SCRATCH_OFFSET_MB, direct: bool = True) -> dict:
    if read_label(path) is None:
        raise OpsError(f"{path} heeft geen RPITEST-fixtureheader; er wordt niet naar geschreven")
    n_chunks = size_mb
    start = offset_mb * CHUNK
    fd = os.open(path, _flags(direct))
    f = os.fdopen(fd, "r+b", buffering=0)
    try:
        if f.seek(0, os.SEEK_END) < start + n_chunks * CHUNK:
            raise OpsError(f"{path} is te klein voor een test van {size_mb} MB vanaf {offset_mb} MB")
        buf = mmap.mmap(-1, CHUNK)
        hashes = []

        f.seek(start)
        t0 = time.perf_counter()
        for _ in range(n_chunks):
            data = os.urandom(CHUNK)
            hashes.append(hashlib.sha256(data).digest())
            buf.seek(0)
            buf.write(data)
            if f.write(buf) != CHUNK:
                raise OpsError("onvolledige schrijfbewerking")
        os.fsync(fd)
        write_s = time.perf_counter() - t0

        f.seek(start)
        mismatches = 0
        t0 = time.perf_counter()
        for expected in hashes:
            got = 0
            while got < CHUNK:  # een lees mag korter zijn dan gevraagd
                view = memoryview(buf)[got:]
                n = f.readinto(view)
                if not n:
                    raise OpsError("onverwacht einde bij terugleggen")
                got += n
            if hashlib.sha256(buf).digest() != expected:
                mismatches += 1
        read_s = time.perf_counter() - t0
    except OSError as exc:
        raise OpsError(f"I/O-fout op {path}: {exc}") from exc
    finally:
        f.close()
    return {
        "mb": n_chunks,
        "write_mb_s": round(n_chunks / max(write_s, 1e-6), 1),
        "read_mb_s": round(n_chunks / max(read_s, 1e-6), 1),
        "mismatching_chunks": mismatches,
    }
