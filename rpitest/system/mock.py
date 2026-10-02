"""Gesimuleerde testpi + DUT voor netwerk, wifi en bluetooth, met foutinjectie.

Fouten (via --fault op de opdrachtregel):
  eth_100        DUT onderhandelt slechts 100 Mb/s
  eth_errors     DUT telt veel ethernetfouten tijdens de test
  eth_slow       lage doorvoer
  eth_loss       pakketverlies op de kabel
  no_wifi        DUT heeft geen wifi-interface
  wifi_5g_dead   5 GHz werkt niet op de DUT
  wifi_weak      zwak wifi-signaal op de DUT
  no_bt          DUT heeft geen bluetooth-controller
  bt_dut_rx_dead DUT hoort geen andere bluetooth-apparaten
  bt_dut_tx_dead niemand hoort de DUT
  tester_no_wifi / tester_no_bt   de testpi mist wifi / bluetooth
  usb_slotN_dead / _usb2 / _corrupt / _slow   (N = 1..4) stick niet gevonden / valt terug op USB2 /
                 datafouten / traag
  usb_no_sticks  geen enkele teststick aanwezig (fixture niet aangesloten)
  usb_overcurrent / usb_disconnect   kernelmeldingen tijdens de test
"""

from __future__ import annotations

from .. import config
from .ops import OpsError, SystemOps

TESTER, DUT = "T", "D"
USB_SLOT_FAULTS = {f"usb_slot{n}_{kind}" for n in range(1, 5) for kind in ("dead", "usb2", "corrupt", "slow")}
KNOWN_FAULTS = frozenset(USB_SLOT_FAULTS | {"usb_no_sticks", "usb_overcurrent", "usb_disconnect"} | {
    "eth_100", "eth_errors", "eth_slow", "eth_loss", "no_wifi", "wifi_5g_dead", "wifi_weak",
    "no_bt", "bt_dut_rx_dead", "bt_dut_tx_dead", "tester_no_wifi", "tester_no_bt",
})
BT_ADDRESS = {TESTER: "DC:A6:32:00:00:01", DUT: "DC:A6:32:00:00:02"}
HOTSPOT_IP, DUT_WIFI_IP = "10.42.0.1", "10.42.0.57"


class MockEnv:
    def __init__(self, faults=()):
        unknown = set(faults) - KNOWN_FAULTS
        if unknown:
            raise ValueError(f"onbekende fout(en): {sorted(unknown)}")
        self.faults = set(faults)
        self.hotspot: dict | None = None
        self.dut_connected = False
        self.discoverable = {TESTER: False, DUT: False}
        self.dut_errors = 0

    def ops(self, side: str) -> MockOps:
        return MockOps(self, side)


class MockOps(SystemOps):
    def __init__(self, env: MockEnv, side: str):
        self._env = env
        self._side = side

    def _fault(self, name: str) -> bool:
        return name in self._env.faults

    # --- wired netwerk ---
    def net_iface_info(self) -> dict:
        speed = 100 if self._side == DUT and self._fault("eth_100") else 1000
        errors = self._env.dut_errors if self._side == DUT else 0
        return {"name": "eth0", "operstate": "up", "carrier": 1, "speed_mbit": speed, "duplex": "full",
                "mac": "dc:a6:32:00:00:0" + ("2" if self._side == DUT else "1"),
                "stats": {"rx_packets": 1000, "tx_packets": 1000, "rx_errors": errors, "tx_errors": 0,
                          "rx_crc_errors": 0, "rx_dropped": 0, "tx_dropped": 0}}

    def ping(self, host: str, count: int) -> dict:
        wired = host in (config.TESTER_IP, config.DUT_IP)
        wifi = self._env.dut_connected and host in (HOTSPOT_IP, DUT_WIFI_IP)
        if not (wired or wifi):
            return {"sent": count, "received": 0, "loss_pct": 100.0, "rtt_avg_ms": None, "rtt_max_ms": None}
        lost = count // 5 if wired and self._fault("eth_loss") else 0
        return {"sent": count, "received": count - lost, "loss_pct": 100.0 * lost / count,
                "rtt_avg_ms": 0.3 if wired else 4.0, "rtt_max_ms": 0.9 if wired else 12.0}

    def iperf3_server_start(self) -> None:
        pass

    def iperf3_server_stop(self) -> None:
        pass

    def iperf3_client(self, host: str, seconds: int, reverse: bool) -> dict:
        if self._fault("eth_errors"):
            self._env.dut_errors += 250
        return {"mbit_per_s": 94.0 if self._fault("eth_slow") or self._fault("eth_100") else 941.0, "retransmits": 0}

    # --- wifi ---
    def _has_wifi(self) -> bool:
        return not self._fault("no_wifi" if self._side == DUT else "tester_no_wifi")

    def wifi_info(self) -> dict:
        return {"ifaces": ["wlan0"] if self._has_wifi() else [], "rfkill": [], "regdom": "country BE (mock)"}

    def wifi_scan(self) -> list[dict]:
        ap = self._env.hotspot
        if not ap or not self._has_wifi() or (ap["band"] == "a" and self._fault("wifi_5g_dead")):
            return []
        return [{"ssid": ap["ssid"], "signal_pct": 80, "bssid": "AA:BB:CC:00:00:01",
                 "freq_mhz": 5180 if ap["band"] == "a" else 2437}]

    def wifi_connect(self, ssid: str, password: str) -> dict:
        if not any(n["ssid"] == ssid for n in self.wifi_scan()):
            raise OpsError(f"nmcli faalde: netwerk {ssid} niet gevonden")
        self._env.dut_connected = True
        return {"ip": DUT_WIFI_IP}

    def wifi_link(self) -> dict:
        if not self._env.dut_connected:
            return {"connected": False, "ip": None}
        ap = self._env.hotspot
        return {"connected": True, "ssid": ap["ssid"], "freq_mhz": 5180 if ap["band"] == "a" else 2437,
                "signal_dbm": -80.0 if self._fault("wifi_weak") else -48.0, "tx_mbit": 150.0, "rx_mbit": 150.0,
                "ip": DUT_WIFI_IP}

    def wifi_forget(self) -> None:
        self._env.dut_connected = False

    def wifi_hotspot_start(self, ssid: str, password: str, band: str, channel: int) -> dict:
        self._env.hotspot = {"ssid": ssid, "band": band, "channel": channel}
        return {"ip": HOTSPOT_IP}

    def wifi_hotspot_stop(self) -> None:
        self._env.hotspot = None
        self._env.dut_connected = False

    # --- bluetooth ---
    def bt_info(self) -> dict:
        present = not self._fault("no_bt" if self._side == DUT else "tester_no_bt")
        return {"present": present, "address": BT_ADDRESS[self._side] if present else None,
                "powered": present, "rfkill": []}

    def bt_scan(self, seconds: int, forget_mac: str | None = None) -> list[dict]:
        other = TESTER if self._side == DUT else DUT
        if not self._env.discoverable[other]:
            return []
        if self._side == DUT and self._fault("bt_dut_rx_dead"):
            return []
        if self._side == TESTER and self._fault("bt_dut_tx_dead"):
            return []
        return [{"address": BT_ADDRESS[other], "name": "mock", "rssi": -52}]

    def bt_discoverable(self, enabled: bool) -> None:
        self._env.discoverable[self._side] = enabled

    # --- usb ---
    def usb_scan(self) -> list[dict]:
        if self._fault("usb_no_sticks"):
            return []
        devices = []
        for n in range(1, 5):
            if self._fault(f"usb_slot{n}_dead"):
                continue
            usb3 = n <= 2 and not self._fault(f"usb_slot{n}_usb2")
            devices.append({"path": f"{2 if usb3 else 1}-1.{n}", "vid": "0781", "pid": "5581",
                            "manufacturer": "Mock", "product": f"Stick {n}", "serial": f"MOCK{n}",
                            "speed_mbit": 5000.0 if usb3 else 480.0, "is_hub": False, "block": f"sd{'abcd'[n - 1]}",
                            "size_bytes": 8 * 1024 ** 3, "fixture_label": f"SLOT{n}"})
        return devices

    def usb_storage_test(self, block: str, size_mb: int) -> dict:
        n = "abcd".index(block[-1]) + 1
        fast = n <= 2 and not self._fault(f"usb_slot{n}_usb2")
        slow = self._fault(f"usb_slot{n}_slow")
        return {"mb": size_mb, "write_mb_s": 1.5 if slow else (80.0 if fast else 20.0),
                "read_mb_s": 2.0 if slow else (180.0 if fast else 35.0),
                "mismatching_chunks": 3 if self._fault(f"usb_slot{n}_corrupt") else 0}

    def usb_uptime(self) -> float:
        return 100.0

    def usb_kernel_events(self) -> list[dict]:
        events = []
        if self._fault("usb_overcurrent"):
            events.append({"ts": 120.0, "category": "overcurrent", "text": "usb usb1-port2: over-current condition"})
        if self._fault("usb_disconnect"):
            events.append({"ts": 130.0, "category": "disconnect", "text": "usb 1-1.3: USB disconnect, device number 4"})
        return events
