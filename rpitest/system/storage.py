"""Lees/schrijftest op de USB-teststicks.

Veiligheid: er wordt alleen geschreven naar een apparaat dat
  - een blokapparaat is (geen gewoon bestand, geen symlink naar iets anders),
  - exclusief geopend kan worden (O_EXCL: Linux weigert een gemount of geclaimd apparaat),
  - op dezelfde bestandsbeschrijver als waarop geschreven wordt onze header (MAGIC + label) in sector 0 heeft,
  - en dan uitsluitend in een testgebied ver voorbij het begin van de stick.
Een stick van een student die toevallig in de TEST-CLIENT zit, heeft die header niet en blijft onaangeroerd."""

from __future__ import annotations

import errno
import hashlib
import mmap
import os
import re
import stat
import time

from .ops import OpsError

MAGIC = b"RPITEST-FIXTURE\0"
SECTOR = 512
HEADER_READ = 4096  # veelvoud van 512 en 4096: ook geldig voor O_DIRECT op een schijf met 4 kB-sectoren
CHUNK = 1 << 20  # 1 MiB; veelvoud van de sectorgrootte en pagina-uitgelijnd via mmap
MAX_LABEL = 32
SCRATCH_OFFSET_MB = 16


def make_header(label: str) -> bytes:
    raw = label.encode("ascii")
    if not 1 <= len(raw) <= MAX_LABEL or not label.isprintable():
        raise ValueError(f"label moet 1 tot {MAX_LABEL} afdrukbare ASCII-tekens zijn")
    return (MAGIC + raw).ljust(SECTOR, b"\0")


def _flags(direct: bool, exclusive: bool) -> int:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    if direct:
        flags |= getattr(os, "O_DIRECT", 0)
    if exclusive:
        flags |= os.O_EXCL  # op een blokapparaat: weigert met EBUSY als het gemount of geclaimd is
    return flags


def _kind(path: str) -> tuple[str, int]:
    """('block' | 'file' | 'other', apparaatnummer)"""
    try:
        st = os.stat(path)
    except OSError as exc:
        raise OpsError(f"{path} niet te benaderen: {exc}") from exc
    if stat.S_ISBLK(st.st_mode):
        return "block", st.st_rdev
    return ("file" if stat.S_ISREG(st.st_mode) else "other"), 0


def _open_checked(path: str, direct: bool, allow_file: bool) -> int:
    """Opent het apparaat één keer, exclusief, en controleert dat het nog hetzelfde apparaat is.
    Gewone bestanden alleen met allow_file (tests)."""
    kind, rdev = _kind(path)
    if kind != "block" and not (kind == "file" and allow_file):
        raise OpsError(f"{path} is geen blokapparaat; er wordt niet naar geschreven")
    try:
        fd = os.open(path, _flags(direct, exclusive=kind == "block"))
    except OSError as exc:
        if exc.errno == errno.EBUSY:
            raise OpsError(f"{path} is in gebruik (gekoppeld of door een ander proces geclaimd)") from exc
        raise OpsError(f"{path} openen mislukt: {exc}") from exc
    if kind == "block":
        st = os.fstat(fd)
        if not stat.S_ISBLK(st.st_mode) or st.st_rdev != rdev:
            os.close(fd)
            raise OpsError(f"{path} is tussen de controle en het openen vervangen; er wordt niet naar geschreven")
    return fd


def is_mounted(block: str, mounts_text: str) -> bool:
    """Staat dit apparaat (of een partitie ervan) in /proc/mounts?"""
    pattern = re.compile(rf"^/dev/{re.escape(block)}(\d+)?\s", re.M)
    return bool(pattern.search(mounts_text))


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


def write_label(path: str, label: str, allow_file: bool = False) -> None:
    """Schrijft de header in sector 0. De aanroeper moet eerst gecontroleerd hebben dat het
    om een USB-stick gaat die gewist mag worden; hier wordt nog gecontroleerd dat het een
    blokapparaat is dat exclusief geopend kan worden."""
    header = make_header(label)
    fd = _open_checked(path, direct=False, allow_file=allow_file)
    try:
        os.write(fd, header)
        os.fsync(fd)
    finally:
        os.close(fd)


def run_storage_test(path: str, size_mb: int, offset_mb: int = SCRATCH_OFFSET_MB, direct: bool = True,
                     allow_file: bool = False) -> dict:
    n_chunks = size_mb
    start = offset_mb * CHUNK
    fd = _open_checked(path, direct, allow_file)
    f = os.fdopen(fd, "r+b", buffering=0)
    try:
        buf = mmap.mmap(-1, CHUNK)
        # De header wordt gelezen van dezelfde bestandsbeschrijver als waarop straks geschreven wordt.
        f.seek(0)
        got = f.readinto(memoryview(buf)[:HEADER_READ])
        if got < SECTOR or not bytes(buf[:SECTOR]).startswith(MAGIC):
            raise OpsError(f"{path} heeft geen RPITEST-fixtureheader; er wordt niet naar geschreven")
        if f.seek(0, os.SEEK_END) < start + n_chunks * CHUNK:
            raise OpsError(f"{path} is te klein voor een test van {size_mb} MB vanaf {offset_mb} MB")
        hashes = []

        # Alleen de I/O zelf wordt gemeten: urandom, sha256 en het kopiëren naar de buffer horen niet bij de
        # snelheid van de stick (op een Pi 4 zonder crypto-extensies zou dat de MB/s merkbaar drukken).
        f.seek(start)
        write_s = 0.0
        for _ in range(n_chunks):
            data = os.urandom(CHUNK)
            hashes.append(hashlib.sha256(data).digest())
            buf.seek(0)
            buf.write(data)
            t0 = time.perf_counter()
            written = f.write(buf)
            write_s += time.perf_counter() - t0
            if written != CHUNK:
                raise OpsError("onvolledige schrijfbewerking")
        t0 = time.perf_counter()
        os.fsync(fd)
        write_s += time.perf_counter() - t0

        f.seek(start)
        mismatches = 0
        read_s = 0.0
        for expected in hashes:
            got = 0
            while got < CHUNK:  # een lees mag korter zijn dan gevraagd
                view = memoryview(buf)[got:]
                t0 = time.perf_counter()
                n = f.readinto(view)
                read_s += time.perf_counter() - t0
                if not n:
                    raise OpsError("onverwacht einde bij terugleggen")
                got += n
            if hashlib.sha256(buf).digest() != expected:
                mismatches += 1
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
