"""Wat TEST-SERVER en TEST-CLIENT op systeemniveau kunnen doen (netwerk, wifi, bluetooth).

LinuxOps doet het echt (subprocess), MockOps simuleert het. Op de TEST-CLIENT stelt de agent een
beperkte, gevalideerde deelverzameling van deze methodes beschikbaar aan de TEST-SERVER.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class OpsError(Exception):
    """Een systeemopdracht is mislukt (tool ontbreekt, time-out, foutmelding)."""


class SystemOps(ABC):
    # --- wired netwerk ---
    @abstractmethod
    def net_iface_info(self) -> dict:
        """{'name','operstate','carrier','speed_mbit','duplex','mac','stats':{...}} van de ethernetpoort."""

    @abstractmethod
    def ping(self, host: str, count: int) -> dict:
        """{'sent','received','loss_pct','rtt_avg_ms','rtt_max_ms'}"""

    @abstractmethod
    def iperf3_server_start(self) -> None: ...

    @abstractmethod
    def iperf3_server_stop(self) -> None: ...

    @abstractmethod
    def iperf3_client(self, host: str, seconds: int, reverse: bool) -> dict:
        """{'mbit_per_s','retransmits'}; reverse=True: de server stuurt."""

    # --- wifi ---
    @abstractmethod
    def wifi_info(self) -> dict:
        """{'ifaces': [...], 'rfkill': [...], 'country': str}"""

    @abstractmethod
    def wifi_scan(self) -> list[dict]:
        """[{'ssid','signal_pct','freq_mhz','bssid'}]"""

    @abstractmethod
    def wifi_connect(self, ssid: str, password: str) -> dict:
        """Verbind en geef {'ip'} terug."""

    @abstractmethod
    def wifi_link(self) -> dict:
        """{'connected','ssid','freq_mhz','signal_dbm','tx_mbit','rx_mbit','ip'}"""

    @abstractmethod
    def wifi_forget(self) -> None: ...

    @abstractmethod
    def wifi_hotspot_start(self, ssid: str, password: str, band: str, channel: int) -> dict:
        """Start een accesspoint en geef {'ip'} terug (enkel TEST-SERVER)."""

    @abstractmethod
    def wifi_hotspot_stop(self) -> None: ...

    # --- bluetooth ---
    @abstractmethod
    def bt_info(self) -> dict:
        """{'present','address','powered'}"""

    @abstractmethod
    def bt_scan(self, seconds: int, forget_mac: str | None = None) -> list[dict]:
        """[{'address','name','rssi'}]; forget_mac wordt eerst vergeten zodat hij als nieuw verschijnt."""

    @abstractmethod
    def bt_discoverable(self, enabled: bool) -> None: ...

    # --- usb ---
    @abstractmethod
    def usb_scan(self) -> list[dict]:
        """Alle niet-root-hub USB-apparaten: {'path','vid','pid','manufacturer','product','serial',
        'speed_mbit','is_hub','block','size_bytes','fixture_label'}"""

    @abstractmethod
    def usb_storage_test(self, block: str, size_mb: int) -> dict:
        """Schrijf/lees/vergelijk op een voorbereide teststick: {'mb','write_mb_s','read_mb_s','mismatching_chunks'}"""

    @abstractmethod
    def usb_uptime(self) -> float:
        """Seconden sinds opstarten, op dezelfde klok als de tijdstempels van usb_kernel_events."""

    @abstractmethod
    def usb_kernel_events(self) -> list[dict]:
        """USB-problemen uit het kernellogboek: [{'ts','category','text'}]"""

    # --- voeding, temperatuur en belasting ---
    @abstractmethod
    def power_sample(self) -> dict:
        """{'temp_c','freq_mhz','freq_max_mhz','throttled' (bitmasker of None),'volts':{...},
        'cores_online','cores_present'}; ontbrekende metingen zijn None."""

    @abstractmethod
    def stress_start(self, seconds: int, ram_mb: int) -> None:
        """Start CPU- en RAM-belasting op de achtergrond."""

    @abstractmethod
    def stress_poll(self) -> dict:
        """{'running': bool, 'elapsed': seconden}"""

    @abstractmethod
    def stress_result(self) -> dict:
        """{'cpu': [{'rounds','bad'}, ...], 'ram': {'passes','bad','mb'} of None, 'errors': [...]}"""

    @abstractmethod
    def stress_stop(self) -> None: ...

    @abstractmethod
    def power_off(self) -> None:
        """Schakel deze Pi uit. Keert terug voordat de uitschakeling begint, zodat een antwoord nog aankomt."""
