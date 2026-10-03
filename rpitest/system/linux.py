"""Echte systeemopdrachten op Raspberry Pi OS Trixie (NetworkManager, BlueZ, iperf3, iw).

Alle commando's worden als lijst van argumenten uitgevoerd (nooit via een shell), zodat
waarden van de TEST-SERVER geen commando's kunnen injecteren."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .. import config
from . import parsers, storage
from .ops import OpsError, SystemOps

STAT_FIELDS = ("rx_packets", "tx_packets", "rx_errors", "tx_errors", "rx_crc_errors", "rx_dropped", "tx_dropped")


@dataclass
class ShellResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Shell:
    def run(self, argv: list[str], timeout: float = 30) -> ShellResult:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        except FileNotFoundError:
            return ShellResult(127, "", f"{argv[0]}: niet gevonden (pakket niet geinstalleerd?)")
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return ShellResult(124, out, f"{argv[0]}: time-out na {timeout}s")
        return ShellResult(p.returncode, p.stdout, p.stderr)


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    try:
        return int(_read(path) or "")
    except ValueError:
        return None


def list_ifaces(root: Path = Path("/")) -> tuple[list[str], list[str]]:
    """(ethernet, wifi) fysieke interfaces; virtuele (docker, bridges, loopback) vallen af."""
    base = root / "sys/class/net"
    eth, wifi = [], []
    if not base.is_dir():
        return eth, wifi
    for d in sorted(base.iterdir()):
        if d.name == "lo":
            continue
        if (d / "wireless").exists() or (d / "phy80211").exists():
            wifi.append(d.name)
        elif (d / "device").exists():
            eth.append(d.name)
    return eth, wifi


def _read_float(path: Path) -> float | None:
    try:
        return float(_read(path) or "")
    except ValueError:
        return None


def is_usb_device_name(name: str) -> bool:
    """'1-1.3' is een apparaat; 'usb1' (root hub) en '1-1.3:1.0' (interface) zijn dat niet."""
    return ":" not in name and not name.startswith("usb")


def usb_block_devices(root: Path = Path("/")) -> dict[str, str]:
    """USB-pad -> blokapparaatnaam (bv. '1-1.3' -> 'sda')."""
    found = {}
    base = root / "sys/block"
    if not base.is_dir():
        return found
    for d in sorted(base.iterdir()):
        usb_path = parsers.usb_path_from_syspath(os.path.realpath(d))
        if usb_path:
            found[usb_path] = d.name
    return found


def rfkill_state(root: Path = Path("/")) -> list[dict]:
    base = root / "sys/class/rfkill"
    if not base.is_dir():
        return []
    return [{"type": _read(d / "type"), "name": _read(d / "name"),
             "soft_blocked": _read(d / "soft") == "1", "hard_blocked": _read(d / "hard") == "1"}
            for d in sorted(base.iterdir())]


class LinuxOps(SystemOps):
    def __init__(self, shell: Shell | None = None, root: Path = Path("/")):
        self._sh = shell or Shell()
        self._root = root
        self._iperf_server: subprocess.Popen | None = None
        self._bt_proc: subprocess.Popen | None = None
        self._stress: dict | None = None

    # --- hulpfuncties ---
    def _run(self, argv: list[str], timeout: float = 30, check: bool = True) -> ShellResult:
        result = self._sh.run(argv, timeout)
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[:300]
            raise OpsError(f"{' '.join(argv[:3])} faalde ({result.returncode}): {detail}")
        return result

    def _eth(self) -> str:
        eth, _ = list_ifaces(self._root)
        if not eth:
            raise OpsError("geen ethernet-interface gevonden")
        return eth[0]

    def _wlan(self) -> str:
        _, wifi = list_ifaces(self._root)
        if not wifi:
            raise OpsError("geen wifi-interface gevonden")
        return wifi[0]

    def _ip_of(self, iface: str) -> str | None:
        return parsers.parse_ip_addr(self._run(["ip", "-4", "-o", "addr", "show", "dev", iface], check=False).stdout)

    # --- wired netwerk ---
    def net_iface_info(self) -> dict:
        name = self._eth()
        base = self._root / "sys/class/net" / name
        speed = _read_int(base / "speed")
        return {
            "name": name,
            "operstate": _read(base / "operstate"),
            "carrier": _read_int(base / "carrier"),
            "speed_mbit": speed if speed and speed > 0 else None,
            "duplex": _read(base / "duplex"),
            "mac": _read(base / "address"),
            "stats": {f: _read_int(base / "statistics" / f) or 0 for f in STAT_FIELDS},
        }

    def ping(self, host: str, count: int) -> dict:
        result = self._run(["ping", "-c", str(count), "-i", "0.2", "-q", "-W", "1", host],
                           timeout=count * 1.3 + 10, check=False)
        if result.returncode == 127:
            raise OpsError(result.stderr)
        return parsers.parse_ping(result.stdout)

    def iperf3_server_start(self) -> None:
        self.iperf3_server_stop()
        try:
            self._iperf_server = subprocess.Popen(
                ["iperf3", "-s", "-p", str(config.IPERF_PORT)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError as exc:
            raise OpsError("iperf3 niet gevonden (sudo apt install iperf3)") from exc
        time.sleep(0.5)
        if self._iperf_server.poll() is not None:
            err = (self._iperf_server.stderr.read() or "").strip()[:300]
            self._iperf_server = None
            raise OpsError(f"iperf3-server startte niet: {err}")

    def iperf3_server_stop(self) -> None:
        proc, self._iperf_server = self._iperf_server, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def iperf3_client(self, host: str, seconds: int, reverse: bool) -> dict:
        argv = ["iperf3", "-c", host, "-p", str(config.IPERF_PORT), "-t", str(seconds), "-J"]
        if reverse:
            argv.append("-R")
        result = self._run(argv, timeout=seconds + 15, check=False)
        if result.returncode == 127:
            raise OpsError(result.stderr)
        return parsers.parse_iperf3(result.stdout)

    # --- wifi ---
    def wifi_info(self) -> dict:
        _, wifi = list_ifaces(self._root)
        country = self._run(["iw", "reg", "get"], check=False).stdout.strip()
        return {"ifaces": wifi, "rfkill": [r for r in rfkill_state(self._root) if r["type"] == "wlan"],
                "regdom": country[:300]}

    def wifi_scan(self) -> list[dict]:
        iface = self._wlan()
        out = self._run(["nmcli", "-t", "-f", "SSID,SIGNAL,FREQ,BSSID", "dev", "wifi", "list",
                         "ifname", iface, "--rescan", "yes"], timeout=40)
        return parsers.parse_wifi_scan(out.stdout)

    def wifi_connect(self, ssid: str, password: str) -> dict:
        iface = self._wlan()
        self.wifi_forget()
        self._run(["nmcli", "-w", "30", "dev", "wifi", "connect", ssid, "password", password,
                   "ifname", iface, "name", config.WIFI_PROFILE], timeout=45)
        return {"ip": self._ip_of(iface)}

    def wifi_link(self) -> dict:
        iface = self._wlan()
        link = parsers.parse_iw_link(self._run(["iw", "dev", iface, "link"], check=False).stdout)
        link["ip"] = self._ip_of(iface)
        return link

    def wifi_forget(self) -> None:
        self._run(["nmcli", "connection", "delete", "id", config.WIFI_PROFILE], check=False)

    def wifi_hotspot_start(self, ssid: str, password: str, band: str, channel: int) -> dict:
        iface = self._wlan()
        self.wifi_hotspot_stop()
        self._run(["nmcli", "dev", "wifi", "hotspot", "ifname", iface, "con-name", config.WIFI_AP_PROFILE,
                   "ssid", ssid, "band", band, "channel", str(channel), "password", password], timeout=40)
        return {"ip": self._ip_of(iface)}

    def wifi_hotspot_stop(self) -> None:
        self._run(["nmcli", "connection", "delete", "id", config.WIFI_AP_PROFILE], check=False)

    # --- bluetooth ---
    def bt_info(self) -> dict:
        info = parsers.parse_bluetoothctl_show(self._run(["bluetoothctl", "show"], check=False).stdout)
        if info["present"] and not info["powered"]:
            self._run(["bluetoothctl", "power", "on"], check=False)
            info = parsers.parse_bluetoothctl_show(self._run(["bluetoothctl", "show"], check=False).stdout)
        info["rfkill"] = [r for r in rfkill_state(self._root) if r["type"] == "bluetooth"]
        return info

    def bt_scan(self, seconds: int, forget_mac: str | None = None) -> list[dict]:
        if forget_mac:
            self._run(["bluetoothctl", "remove", forget_mac], check=False)
        result = self._run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"],
                           timeout=seconds + 15, check=False)
        if result.returncode == 127:
            raise OpsError(result.stderr)
        return parsers.parse_bluetooth_scan(result.stdout)

    def bt_discoverable(self, enabled: bool) -> None:
        # Een open bluetoothctl-sessie houdt de adapter betrouwbaar zichtbaar zolang we dat willen.
        if self._bt_proc is not None:
            self._send_bt("discoverable off\nquit\n")
            self._bt_proc = None
        if not enabled:
            return
        try:
            self._bt_proc = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, text=True)
        except FileNotFoundError as exc:
            raise OpsError("bluetoothctl niet gevonden (sudo apt install bluez)") from exc
        self._send_bt("power on\npairable off\ndiscoverable on\n")
        time.sleep(1.5)

    def _send_bt(self, text: str) -> None:
        proc = self._bt_proc
        try:
            proc.stdin.write(text)
            proc.stdin.flush()
            if "quit" in text:
                proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()

    # --- usb ---
    def usb_scan(self) -> list[dict]:
        base = self._root / "sys/bus/usb/devices"
        blocks = usb_block_devices(self._root)
        devices = []
        if not base.is_dir():
            return devices
        for d in sorted(base.iterdir()):
            if not is_usb_device_name(d.name):
                continue
            vid = _read(d / "idVendor")
            if vid is None:
                continue
            block = blocks.get(d.name)
            size_sectors = _read_int(self._root / "sys/block" / block / "size") if block else None
            devices.append({
                "path": d.name, "vid": vid, "pid": _read(d / "idProduct"),
                "manufacturer": _read(d / "manufacturer"), "product": _read(d / "product"),
                "serial": _read(d / "serial"), "speed_mbit": _read_float(d / "speed"),
                "is_hub": _read(d / "bDeviceClass") == "09", "block": block,
                "size_bytes": size_sectors * 512 if size_sectors else None,
                "fixture_label": storage.read_label(f"/dev/{block}") if block else None,
            })
        return devices

    def usb_storage_test(self, block: str, size_mb: int) -> dict:
        if not re.fullmatch(r"sd[a-z]{1,2}", block):
            raise OpsError(f"geen toegestaan blokapparaat: {block!r}")
        if parsers.usb_path_from_syspath(os.path.realpath(self._root / "sys/block" / block)) is None:
            raise OpsError(f"{block} is geen USB-apparaat")
        return storage.run_storage_test(f"/dev/{block}", size_mb)

    def usb_uptime(self) -> float:
        uptime = _read(self._root / "proc/uptime")
        try:
            return float((uptime or "").split()[0])
        except (ValueError, IndexError) as exc:
            raise OpsError("uptime niet te lezen") from exc

    def usb_kernel_events(self) -> list[dict]:
        result = self._run(["dmesg"], check=False)
        if result.returncode != 0:
            raise OpsError(f"dmesg faalde ({result.returncode}): {result.stderr.strip()[:200]}")
        return parsers.parse_usb_events(result.stdout)

    # --- voeding, temperatuur en belasting ---
    def power_sample(self) -> dict:
        millideg = _read_int(self._root / "sys/class/thermal/thermal_zone0/temp")
        cpufreq = self._root / "sys/devices/system/cpu/cpu0/cpufreq"
        freq_khz = _read_int(cpufreq / "scaling_cur_freq")
        max_khz = _read_int(cpufreq / "cpuinfo_max_freq")
        throttled = parsers.parse_throttled(self._run(["vcgencmd", "get_throttled"], check=False).stdout)
        volts = parsers.parse_pmic_adc(self._run(["vcgencmd", "pmic_read_adc"], check=False).stdout)
        online = _read(self._root / "sys/devices/system/cpu/online")
        present = _read(self._root / "sys/devices/system/cpu/present")
        return {
            "temp_c": millideg / 1000 if millideg is not None else None,
            "freq_mhz": freq_khz / 1000 if freq_khz else None,
            "freq_max_mhz": max_khz / 1000 if max_khz else None,
            "throttled": throttled,
            "volts": {k: v for k, v in volts.items() if k.endswith("_V")},
            "cores_online": parsers.parse_cpu_list(online) if online else None,
            "cores_present": parsers.parse_cpu_list(present) if present else None,
        }

    def _mem_available_mb(self) -> int:
        for line in (_read(self._root / "proc/meminfo") or "").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
        return 0

    def stress_start(self, seconds: int, ram_mb: int) -> None:
        self.stress_stop()
        ram = min(ram_mb, self._mem_available_mb() // 2)
        base = [sys.executable, "-m", "rpitest.system.stress"]
        workers = [("cpu", [*base, "cpu", "--seconds", str(seconds)]) for _ in range(os.cpu_count() or 1)]
        if ram >= 16:
            workers.append(("ram", [*base, "ram", "--seconds", str(seconds), "--mb", str(ram)]))
        self._stress = {
            "started": time.monotonic(),
            "procs": [(role, subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
                      for role, argv in workers],
        }

    def stress_poll(self) -> dict:
        if self._stress is None:
            return {"running": False, "elapsed": 0.0}
        running = any(proc.poll() is None for _, proc in self._stress["procs"])
        return {"running": running, "elapsed": round(time.monotonic() - self._stress["started"], 1)}

    def stress_result(self) -> dict:
        if self._stress is None:
            raise OpsError("er is geen belastingstest gestart")
        if self.stress_poll()["running"]:
            raise OpsError("belastingstest loopt nog")
        cpu, ram, errors = [], None, []
        for role, proc in self._stress["procs"]:
            out, err = proc.communicate()
            try:
                data = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                errors.append(f"{role}-worker gaf geen resultaat (exit {proc.returncode}): {err.strip()[-200:]}")
                continue
            if role == "cpu":
                cpu.append(data)
            else:
                ram = data
        self._stress = None
        return {"cpu": cpu, "ram": ram, "errors": errors}

    def stress_stop(self) -> None:
        stress, self._stress = self._stress, None
        for _, proc in (stress or {}).get("procs", []):
            if proc.poll() is None:
                proc.kill()
            proc.communicate()

    def close(self) -> None:
        """Ruim alles op wat deze instantie gestart heeft (aanroepen bij afsluiten)."""
        for step in (self.stress_stop, self.iperf3_server_stop, lambda: self.bt_discoverable(False)):
            try:
                step()
            except Exception:
                pass
