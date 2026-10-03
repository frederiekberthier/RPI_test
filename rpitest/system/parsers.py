"""Pure functies die de uitvoer van Linux-tools omzetten naar dicts.

De formaten komen uit het geheugen van de auteur en zijn nog niet tegen echte Pi's gecontroleerd.
Daarom nemen de checks de ruwe uitvoer op in de details van het rapport.
"""

from __future__ import annotations

import json
import re

from .ops import OpsError

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_MAC = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text).replace("\r", "")


def parse_ping(text: str) -> dict:
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received.*?([\d.]+)% packet loss", text, re.S)
    if not m:
        raise OpsError(f"ping-uitvoer niet te lezen: {text.strip()[:200]!r}")
    result = {"sent": int(m[1]), "received": int(m[2]), "loss_pct": float(m[3]),
              "rtt_avg_ms": None, "rtt_max_ms": None}
    rtt = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms", text)
    if rtt:
        result["rtt_avg_ms"] = float(rtt[2])
        result["rtt_max_ms"] = float(rtt[3])
    return result


def parse_iperf3(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise OpsError(f"iperf3-uitvoer is geen JSON: {text.strip()[:200]!r}") from exc
    if "error" in data:
        raise OpsError(f"iperf3: {data['error']}")
    try:
        end = data["end"]
        return {
            "mbit_per_s": round(end["sum_received"]["bits_per_second"] / 1e6, 1),
            "retransmits": end.get("sum_sent", {}).get("retransmits"),
        }
    except KeyError as exc:
        raise OpsError(f"iperf3-uitvoer mist veld {exc}") from exc


def split_terse(line: str) -> list[str]:
    """Splitst een regel van `nmcli -t` op ':' met ondersteuning voor '\\:' en '\\\\'."""
    fields, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
        elif c == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
            i += 1
    fields.append("".join(cur))
    return fields


def parse_wifi_scan(text: str) -> list[dict]:
    """Verwacht `nmcli -t -f SSID,SIGNAL,FREQ,BSSID dev wifi list`."""
    networks = []
    for line in text.splitlines():
        fields = split_terse(line)
        if len(fields) < 4 or not fields[0]:
            continue
        ssid, signal, freq, bssid = fields[:4]
        try:
            networks.append({"ssid": ssid, "signal_pct": int(signal),
                             "freq_mhz": int(freq.split()[0]), "bssid": bssid})
        except (ValueError, IndexError):
            continue
    return networks


def parse_iw_link(text: str) -> dict:
    if "Not connected" in text or not text.strip():
        return {"connected": False}

    def number(pattern: str):
        m = re.search(pattern, text)
        return float(m[1]) if m else None

    ssid = re.search(r"SSID: (.*)", text)
    freq = number(r"freq: (\d+)")
    return {
        "connected": True,
        "ssid": ssid[1].strip() if ssid else None,
        "freq_mhz": int(freq) if freq is not None else None,
        "signal_dbm": number(r"signal: (-?\d+)"),
        "tx_mbit": number(r"tx bitrate: ([\d.]+)"),
        "rx_mbit": number(r"rx bitrate: ([\d.]+)"),
    }


def parse_ip_addresses(text: str) -> dict[str, str]:
    """`ip -4 -o addr show` -> {interface: eerste IPv4-adres}"""
    found: dict[str, str] = {}
    for m in re.finditer(r"^\d+:\s+(\S+)\s+inet (\d+\.\d+\.\d+\.\d+)/", text, re.M):
        found.setdefault(m[1], m[2])
    return found


def parse_ip_addr(text: str) -> str | None:
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", text)
    return m[1] if m else None


def parse_bluetoothctl_show(text: str) -> dict:
    text = strip_ansi(text)
    m = re.search(rf"Controller ({_MAC})", text)
    if not m:
        return {"present": False, "address": None, "powered": False}
    powered = re.search(r"Powered: (yes|no)", text)
    return {"present": True, "address": m[1].upper(), "powered": bool(powered and powered[1] == "yes")}


def parse_bluetooth_scan(text: str) -> list[dict]:
    """Verwerkt de uitvoer van `bluetoothctl --timeout N scan on`.

    Een apparaat telt als gezien bij een [NEW]-regel of een [CHG]-regel met RSSI."""
    devices: dict[str, dict] = {}
    for line in strip_ansi(text).splitlines():
        if "[DEL]" in line:
            continue
        m = re.search(rf"\[(NEW|CHG)\] Device ({_MAC})(?: (.*))?", line)
        if not m:
            continue
        kind, address, rest = m[1], m[2].upper(), (m[3] or "").strip()
        dev = devices.setdefault(address, {"address": address, "name": None, "rssi": None, "seen": False})
        rssi = re.search(r"RSSI: (?:0x[0-9a-fA-F]+ \()?(-?\d+)\)?", rest)
        if kind == "NEW":
            dev["seen"] = True
            if rest and not rest.startswith(("RSSI", "ManufacturerData", "UUIDs")):
                dev["name"] = rest
        if rssi:
            dev["seen"] = True
            dev["rssi"] = int(rssi[1])
        name = re.match(r"(?:Name|Alias): (.*)", rest)
        if name:
            dev["name"] = name[1].strip()
    return [{k: v for k, v in d.items() if k != "seen"} for d in devices.values() if d["seen"]]


_USB_PATH = re.compile(r"/(\d+-\d+(?:\.\d+)*):\d+\.\d+(?:/|$)")


def usb_path_from_syspath(path: str) -> str | None:
    """Het USB-pad (bv. '1-1.3') waaraan een sysfs-pad van een blokapparaat hangt."""
    found = _USB_PATH.findall(path.replace("\\", "/"))
    return found[-1] if found else None


_EVENT_PATTERNS = (
    ("overcurrent", re.compile(r"over-?current", re.I)),
    ("enumerate", re.compile(
        r"unable to enumerate|cannot enumerate|device not accepting address|device descriptor read/\w+, error"
        r"|unable to read config index|Cannot enable\. Maybe the USB cable is bad|disabled by hub", re.I)),
    ("xhci", re.compile(r"xhci.*(?:HC died|host (?:not halted|controller not responding)|command timed out"
                        r"|Timeout while waiting|died)", re.I)),
    ("disconnect", re.compile(r"USB disconnect, device number", re.I)),
    ("reset", re.compile(r"reset (?:low|full|high|super)[- ]?speed(?:plus)? USB device number|"
                         r"reset SuperSpeed(?: Plus)? USB device number", re.I)),
)
_DMESG_LINE = re.compile(r"^(?:<\d+>)?\[\s*(\d+\.\d+)\]\s*(.*)$")


def parse_usb_events(dmesg_text: str) -> list[dict]:
    """USB-gerelateerde problemen uit `dmesg`: [{'ts','category','text'}]."""
    events = []
    for line in dmesg_text.splitlines():
        m = _DMESG_LINE.match(line.strip())
        ts, text = (float(m[1]), m[2]) if m else (0.0, line.strip())
        if not text:
            continue
        for category, pattern in _EVENT_PATTERNS:
            if pattern.search(text):
                events.append({"ts": ts, "category": category, "text": text})
                break
    return events


# Bits van `vcgencmd get_throttled` (documentatie van Raspberry Pi)
THROTTLED_BITS = {
    0: "undervoltage_now", 1: "freq_capped_now", 2: "throttled_now", 3: "soft_temp_limit_now",
    16: "undervoltage_occurred", 17: "freq_capped_occurred", 18: "throttled_occurred",
    19: "soft_temp_limit_occurred",
}


def parse_throttled(text: str) -> int | None:
    """'throttled=0x50005' -> 0x50005"""
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", text)
    return int(m[1], 16) if m else None


def decode_throttled(value: int | None) -> dict[str, bool]:
    return {name: bool(value and value & (1 << bit)) for bit, name in THROTTLED_BITS.items()}


def parse_pmic_adc(text: str) -> dict[str, float]:
    """`vcgencmd pmic_read_adc` (Pi 5): regels als 'EXT5V_V volt(24)=4.94V' -> {'EXT5V_V': 4.94}."""
    values = {}
    for m in re.finditer(r"^\s*(\w+)\s+(?:volt|current)\(\d+\)=([\d.]+)[AV]", text, re.M):
        values[m[1]] = float(m[2])
    return values


def parse_cpu_list(text: str) -> int:
    """Aantal cpu's in een lijst als '0-3' of '0,2-3'."""
    total = 0
    for part in text.strip().split(","):
        if not part:
            continue
        low, _, high = part.partition("-")
        total += int(high or low) - int(low) + 1
    return total
