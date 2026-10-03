"""Identificatie van de Pi waarop dit draait (voor TEST-SERVER én TEST-CLIENT)."""

from __future__ import annotations

import math
import platform
from pathlib import Path


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(errors="replace").replace("\x00", "").strip()
    except OSError:
        return None


def _cpuinfo_field(cpuinfo: str | None, key: str) -> str | None:
    for line in (cpuinfo or "").splitlines():
        name, _, value = line.partition(":")
        if name.strip() == key:
            return value.strip()
    return None


def _nominal_ram_mb(mem_total_kb: int) -> int:
    """MemTotal is iets lager dan het echte geheugen; rond af naar 1/2/4/8/16 GB."""
    gb = max(1, math.ceil(mem_total_kb / 1024 / 1024))
    return 2 ** math.ceil(math.log2(gb)) * 1024


def pi_info(root: Path = Path("/")) -> dict:
    cpuinfo = _read(root, "proc/cpuinfo")
    info: dict = {
        "model": _read(root, "proc/device-tree/model") or "onbekend",
        "serial": _cpuinfo_field(cpuinfo, "Serial") or _read(root, "sys/firmware/devicetree/base/serial-number")
        or "onbekend",
        "revision": _cpuinfo_field(cpuinfo, "Revision") or "onbekend",
        "kernel": platform.release(),
    }
    meminfo = _read(root, "proc/meminfo") or ""
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            kb = int(line.split()[1])
            info["mem_total_kb"] = kb
            info["ram_mb"] = _nominal_ram_mb(kb)
    return info
