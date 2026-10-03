"""Gesimuleerde TEST-SERVER + TEST-CLIENT voor netwerk, wifi en bluetooth, met foutinjectie.

Fouten (via --fault op de opdrachtregel):
  eth_100        de ethernetlink onderhandelt slechts 100 Mb/s (beide kanten)
  eth_errors     TEST-CLIENT telt veel ethernetfouten tijdens de test
  eth_slow       lage doorvoer
  eth_loss       pakketverlies op de kabel
  no_wifi        TEST-CLIENT heeft geen wifi-interface
  wifi_5g_dead   5 GHz werkt niet op de TEST-CLIENT
  wifi_weak      zwak wifi-signaal op de TEST-CLIENT
  no_bt          TEST-CLIENT heeft geen bluetooth-controller
  bt_client_rx_dead TEST-CLIENT hoort geen andere bluetooth-apparaten
  bt_client_tx_dead niemand hoort de TEST-CLIENT
  server_no_wifi / server_no_bt   de TEST-SERVER mist wifi / bluetooth
  usb_slotN_dead / _usb2 / _corrupt / _slow   (N = 1..4) stick niet gevonden / valt terug op USB2 /
                 datafouten / traag
  usb_no_sticks  geen enkele teststick aanwezig (fixture niet aangesloten)
  usb_overcurrent / usb_disconnect   kernelmeldingen tijdens de test
  power_undervolt / power_undervolt_history   onderspanning nu / alleen sinds opstarten
  power_hot / power_warm / power_throttle     85+ graden / 80+ graden / klokfrequentie gedrukt
  power_cpu_error / power_ram_error / power_core_missing   rekenfouten / geheugenfouten / een kern minder
  power_no_sensor   temperatuursensor niet leesbaar
  power_dip / power_throttle_blip   korte onderspanning / korte throttle tussen twee metingen (kleverige bits)
"""

from __future__ import annotations

from .. import config
from .ops import OpsError, SystemOps

SERVER, CLIENT = "S", "C"
USB_SLOT_FAULTS = {f"usb_slot{n}_{kind}" for n in range(1, 5) for kind in ("dead", "usb2", "corrupt", "slow")}
POWER_FAULTS = {"power_undervolt", "power_undervolt_history", "power_hot", "power_warm", "power_throttle",
                "power_cpu_error", "power_ram_error", "power_core_missing", "power_no_sensor", "power_dip",
                "power_throttle_blip"}
KNOWN_FAULTS = frozenset(USB_SLOT_FAULTS | POWER_FAULTS | {"usb_no_sticks", "usb_overcurrent", "usb_disconnect"} | {
    "eth_100", "eth_errors", "eth_slow", "eth_loss", "no_wifi", "wifi_5g_dead", "wifi_weak",
    "no_bt", "bt_client_rx_dead", "bt_client_tx_dead", "server_no_wifi", "server_no_bt",
})
BT_ADDRESS = {SERVER: "DC:A6:32:00:00:01", CLIENT: "DC:A6:32:00:00:02"}
HOTSPOT_IP, CLIENT_WIFI_IP = "10.42.0.1", "10.42.0.57"


class MockEnv:
    def __init__(self, faults=()):
        unknown = set(faults) - KNOWN_FAULTS
        if unknown:
            raise ValueError(f"onbekende fout(en): {sorted(unknown)}")
        self.faults = set(faults)
        self.hotspot: dict | None = None
        self.client_connected = False
        self.discoverable = {SERVER: False, CLIENT: False}
        self.client_errors = 0
        self.stress_polls_left = 0
        self.stress_polls_done = 0
        self.stress_active = False

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
        speed = 100 if self._fault("eth_100") else 1000  # beide kanten van de kabel onderhandelen hetzelfde
        errors = self._env.client_errors if self._side == CLIENT else 0
        return {"name": "eth0", "operstate": "up", "carrier": 1, "speed_mbit": speed, "duplex": "full",
                "mac": "dc:a6:32:00:00:0" + ("2" if self._side == CLIENT else "1"),
                "stats": {"rx_packets": 1000, "tx_packets": 1000, "rx_errors": errors, "tx_errors": 0,
                          "rx_crc_errors": 0, "rx_dropped": 0, "tx_dropped": 0}}

    def ping(self, host: str, count: int) -> dict:
        wired = host in (config.SERVER_IP, config.CLIENT_IP)
        wifi = self._env.client_connected and host in (HOTSPOT_IP, CLIENT_WIFI_IP)
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
            self._env.client_errors += 250
        return {"mbit_per_s": 94.0 if self._fault("eth_slow") or self._fault("eth_100") else 941.0, "retransmits": 0}

    # --- wifi ---
    def _has_wifi(self) -> bool:
        return not self._fault("no_wifi" if self._side == CLIENT else "server_no_wifi")

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
        self._env.client_connected = True
        return {"ip": CLIENT_WIFI_IP}

    def wifi_link(self) -> dict:
        if not self._env.client_connected:
            return {"connected": False, "ip": None}
        ap = self._env.hotspot
        return {"connected": True, "ssid": ap["ssid"], "freq_mhz": 5180 if ap["band"] == "a" else 2437,
                "signal_dbm": -80.0 if self._fault("wifi_weak") else -48.0, "tx_mbit": 150.0, "rx_mbit": 150.0,
                "ip": CLIENT_WIFI_IP}

    def wifi_forget(self) -> None:
        self._env.client_connected = False

    def wifi_hotspot_start(self, ssid: str, password: str, band: str, channel: int) -> dict:
        self._env.hotspot = {"ssid": ssid, "band": band, "channel": channel}
        return {"ip": HOTSPOT_IP}

    def wifi_hotspot_stop(self) -> None:
        self._env.hotspot = None
        self._env.client_connected = False

    # --- bluetooth ---
    def bt_info(self) -> dict:
        present = not self._fault("no_bt" if self._side == CLIENT else "server_no_bt")
        return {"present": present, "address": BT_ADDRESS[self._side] if present else None,
                "powered": present, "rfkill": []}

    def bt_scan(self, seconds: int, forget_mac: str | None = None) -> list[dict]:
        other = SERVER if self._side == CLIENT else CLIENT
        if not self._env.discoverable[other]:
            return []
        if self._side == CLIENT and self._fault("bt_client_rx_dead"):
            return []
        if self._side == SERVER and self._fault("bt_client_tx_dead"):
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

    # --- voeding, temperatuur en belasting ---
    STRESS_POLLS = 4  # hoeveel keer stress_poll 'nog bezig' meldt

    def power_sample(self) -> dict:
        env = self._env
        loaded = env.stress_active
        temp = 42.0 + (12.0 * min(env.stress_polls_done, 3) / 3 if loaded else 0.0)
        if not loaded and env.stress_polls_done > 0:
            temp = 50.0  # na afloop nog warm, maar de belasting is weg
        if loaded and self._fault("power_hot"):
            temp = 87.0
        elif loaded and self._fault("power_warm"):
            temp = 81.0
        throttled = 0
        if self._fault("power_undervolt_history"):
            throttled |= 1 << 16
        if loaded and self._fault("power_undervolt"):
            throttled |= (1 << 0) | (1 << 16)
        # korte dip/piek tussen twee metingen: alleen de kleverige bits blijven staan, ook nadat de belasting stopt
        happened = env.stress_polls_done >= 2
        if happened and self._fault("power_dip"):
            throttled |= (1 << 16) | (1 << 17) | (1 << 18)
        if happened and self._fault("power_throttle_blip"):
            throttled |= (1 << 17) | (1 << 19)
        throttle = loaded and (self._fault("power_throttle") or self._fault("power_hot"))
        if throttle:
            throttled |= (1 << 3) | (1 << 19)
        volts = {"EXT5V_V": 4.6 if loaded and self._fault("power_undervolt") else 4.95}
        return {
            "temp_c": None if self._fault("power_no_sensor") else temp,
            # in rust zakt de governor naar de rust-klok; alleen onder belasting haalt de Pi het maximum
            "freq_mhz": 1200.0 if throttle else (2400.0 if loaded else 1500.0), "freq_max_mhz": 2400.0,
            "throttled": throttled, "volts": volts,
            "cores_online": 3 if self._fault("power_core_missing") else 4, "cores_present": 4,
        }

    def stress_start(self, seconds: int, ram_mb: int) -> None:
        self._env.stress_polls_left = self.STRESS_POLLS
        self._env.stress_polls_done = 0
        self._env.stress_active = True

    def stress_poll(self) -> dict:
        env = self._env
        running = env.stress_polls_left > 0
        if running:
            env.stress_polls_left -= 1
            env.stress_polls_done += 1
        else:
            env.stress_active = False
        return {"running": running, "elapsed": float(env.stress_polls_done * 2)}

    def stress_result(self) -> dict:
        bad_cpu = 2 if self._fault("power_cpu_error") else 0
        cpu = [{"role": "cpu", "rounds": 120, "bad": bad_cpu if i == 0 else 0} for i in range(4)]
        ram = {"role": "ram", "passes": 3, "bad": 5 if self._fault("power_ram_error") else 0, "mb": 256}
        return {"cpu": cpu, "ram": ram, "errors": []}

    def stress_stop(self) -> None:
        self._env.stress_polls_left = 0
        self._env.stress_active = False
